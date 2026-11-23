"""OCR provider: model fallback, image preparation, and refusal detection."""

from __future__ import annotations

import base64
from io import BytesIO

import structlog
from PIL import Image

from common.config import Settings
from common.content_checks import is_model_refusal
from common.llm import OpenAIChatMixin, service_tier_params, unique_models
from .prompts import TRANSCRIPTION_PROMPT
from .text_assembly import PageResult

log = structlog.get_logger(__name__)


def is_blank(image: Image.Image, threshold: int = 5) -> bool:
    """Return ``True`` if the image is pure white (greyscale 255).

    Only synthetic blank pages match; near-white scanner backgrounds do not.
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
        """The OpenAI ``reasoning_effort`` for OCR, or ``None`` for non-OpenAI."""
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

            if not response.choices:
                log.warning("Model returned no choices", model=model, **log_ctx)
                continue

            message = response.choices[0].message
            if message is None or not isinstance(message.content, str | None):
                log.warning("Model returned no usable message", model=model, **log_ctx)
                continue

            text = (message.content or "").strip()

            if is_model_refusal(
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

        Only oversized pages pay for a copy to resize; the caller's image is
        never mutated.
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
