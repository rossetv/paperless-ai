"""OCR provider: model fallback, image preparation, and refusal detection."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Iterable

import structlog
from PIL import Image

from common.config import Settings
from common.llm import OpenAIChatMixin, service_tier_params, unique_models
from .prompts import TRANSCRIPTION_PROMPT
from .text_assembly import PageResult

log = structlog.get_logger(__name__)

# A model response shorter than this threshold that contains a refusal phrase is
# treated as a genuine refusal. Longer responses — which may be real document
# content that happens to contain the phrase (e.g. a denial letter) — are not.
_REFUSAL_DOMINANCE_THRESHOLD_CHARS = 200


def _is_model_refusal(
    text: str, refusal_markers: Iterable[str], refusal_mark: str
) -> bool:
    """Return ``True`` only when *text* is a genuine model refusal.

    Two tiers of detection:

    1. **Hard sentinel** — the *refusal_mark* (e.g. ``"CHATGPT REFUSED TO
       TRANSCRIBE"``): matched unconditionally regardless of response length.
       This sentinel is written by this provider itself; if a downstream model
       echoes it back verbatim the page is genuinely unprocessable.
    2. **Soft phrases** (e.g. ``"i cannot assist"``): treated as a refusal only
       when the response is *dominated* by the phrase — the full response is
       shorter than :data:`_REFUSAL_DOMINANCE_THRESHOLD_CHARS`.  A long response
       containing such a phrase mid-text is real document content (a denial
       letter, a legal notice) and must not be silently discarded.

    This prevents permanent data loss when a scanned document contains common
    refusal-adjacent language, while still catching genuine short refusals
    (CODE_GUIDELINES §1.4 / M5 fix).
    """
    text_lower = text.lower()

    # Hard sentinel: match anywhere, regardless of surrounding text or length.
    if refusal_mark.lower() in text_lower:
        return True

    # Soft markers: only a short response that is essentially nothing but the
    # refusal phrase is genuinely a refusal.
    if len(text) >= _REFUSAL_DOMINANCE_THRESHOLD_CHARS:
        return False
    return any(phrase.lower() in text_lower for phrase in refusal_markers)


def is_blank(image: Image.Image, threshold: int = 5) -> bool:
    """Return ``True`` if the image is pixel-perfect white (greyscale value 255).

    Counts only exact-255 pixels as white; near-white scanner backgrounds
    (values 250–254) are treated as non-blank.  Used to skip synthetically
    blank pages without wasting an API call.  Real-world scans with slight
    off-white backgrounds will not match this check.
    """
    histogram = image.convert("L").histogram()
    return (sum(histogram) - histogram[255]) < threshold


class OcrProvider(OpenAIChatMixin):
    """OCR provider backed by the OpenAI (or Ollama-compatible) chat API.

    Tries each model in ``settings.OCR_MODELS`` in order, falling back to the
    next model when the current one refuses or errors.
    """

    _STAT_KEYS = ("attempts", "refusals", "api_errors", "fallback_successes")

    def __init__(self, settings: Settings):
        self.settings = settings
        self._init_stats()

    @property
    def _provider(self) -> str:
        """Route OCR's chat calls to the OCR step's configured provider."""
        return self.settings.OCR_PROVIDER

    def _reasoning_effort(self) -> str | None:
        """The OpenAI ``reasoning_effort`` for OCR, or ``None`` for non-OpenAI.

        Gated on the OCR step's own provider so non-OpenAI requests never
        include the kwarg.  If an OpenAI model still rejects it,
        ``_create_with_compat`` strips and caches the rejection rather than
        failing the whole fallback chain.
        """
        if self.settings.OCR_PROVIDER != "openai":
            return None
        return self.settings.OCR_REASONING_EFFORT

    def transcribe_image(
        self,
        image: Image.Image,
        doc_id: int | None = None,
        page_num: int | None = None,
    ) -> PageResult:
        """Transcribe a single page image using the configured model chain.

        Returns a blank :class:`PageResult` for blank pages, and a
        ``settings.REFUSAL_MARK`` result when every model refuses or errors.
        """
        log_ctx: dict[str, int] = {}
        if doc_id is not None:
            log_ctx["doc_id"] = doc_id
        if page_num is not None:
            log_ctx["page_num"] = page_num

        if is_blank(image):
            return PageResult(text="", model="")

        payload = self._encode_page(image)

        messages: list[dict[str, object]] = [
            {"role": "system", "content": TRANSCRIPTION_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{payload}",
                            "detail": self.settings.OCR_IMAGE_DETAIL,
                        },
                    },
                ],
            },
        ]

        models_to_try = unique_models(self.settings.OCR_MODELS)
        primary_model = models_to_try[0]

        for model in models_to_try:
            params: dict[str, object] = {
                "model": model,
                "messages": messages,
                "timeout": self.settings.REQUEST_TIMEOUT,
            }
            reasoning_effort = self._reasoning_effort()
            if reasoning_effort is not None:
                params["reasoning_effort"] = reasoning_effort
            if self.settings.OCR_PROVIDER == "openai":
                params.update(
                    service_tier_params(
                        flex_enabled=self.settings.OPENAI_FLEX_TIER,
                        request_timeout=self.settings.REQUEST_TIMEOUT,
                    )
                )

            response = self._create_with_compat(params, model)
            if response is None:
                # _create_with_compat already logged and counted the api_error.
                continue

            text = (response.choices[0].message.content or "").strip()

            if _is_model_refusal(
                text,
                self.settings.OCR_REFUSAL_MARKERS,
                self.settings.REFUSAL_MARK,
            ):
                log.warning("Model refused to transcribe", model=model, **log_ctx)
                self._stats.inc("refusals")
                continue
            if model != primary_model:
                log.info("Fallback model succeeded", model=model, **log_ctx)
                self._stats.inc("fallback_successes")
            return PageResult(text=text, model=model)

        log.error("All models failed or refused to transcribe the page", **log_ctx)
        return PageResult(text=self.settings.REFUSAL_MARK, model="")

    def _encode_page(self, image: Image.Image) -> str:
        """Return the base64 PNG payload for *image*, capped at ``OCR_MAX_SIDE``.

        Only pages whose longer side exceeds the cap are resized, and only those
        pay for a copy — pages already at or below the cap (the common case once
        the PDF is rasterised at target size) are encoded straight from the
        caller's image. The caller's image is never mutated either way: the
        resize happens on a private copy that is closed here, once the payload —
        the only thing that must outlive this call — has been built.
        """
        if max(image.size) <= self.settings.OCR_MAX_SIDE:
            return _image_to_base64_png(image)

        working = image.copy()
        try:
            working.thumbnail((self.settings.OCR_MAX_SIDE, self.settings.OCR_MAX_SIDE))
            return _image_to_base64_png(working)
        finally:
            working.close()


def _image_to_base64_png(image: Image.Image) -> str:
    """Encode *image* as a base64 PNG string, releasing the buffer promptly."""
    with BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
