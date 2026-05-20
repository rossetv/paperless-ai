"""OCR provider with model fallback, image preparation, and refusal detection."""

from __future__ import annotations

import base64
from io import BytesIO

import openai
import structlog
from PIL import Image

from common.config import Settings
from common.llm import OpenAIChatMixin, unique_models
from common.content_checks import is_error_content
from .prompts import TRANSCRIPTION_PROMPT
from .text_assembly import PageResult

log = structlog.get_logger(__name__)


def is_blank(image: Image.Image, threshold: int = 5) -> bool:
    """Return ``True`` if the image is essentially blank (all white).

    Converts to greyscale and checks that the number of non-white pixels
    is below *threshold*.  Used to skip blank pages without wasting an
    API call.
    """
    histogram = image.convert("L").histogram()
    return (sum(histogram) - histogram[255]) < threshold


class OcrProvider(OpenAIChatMixin):
    """OCR provider backed by the OpenAI (or Ollama-compatible) chat API.

    Tries each model in ``settings.AI_MODELS`` in order, falling back to the
    next model when the current one refuses or errors.
    """

    _STAT_KEYS = ("attempts", "refusals", "api_errors", "fallback_successes")

    def __init__(self, settings: Settings):
        self.settings = settings
        self._init_stats()

    def transcribe_image(
        self,
        image: Image.Image,
        doc_id: int | None = None,
        page_num: int | None = None,
    ) -> PageResult:
        """
        Transcribe a single page image using the configured model chain.

        Returns a blank :class:`PageResult` for blank pages and for the case
        where every model refuses or errors — in the latter case the text is
        ``settings.REFUSAL_MARK``.
        """
        log_ctx: dict[str, int] = {}
        if doc_id is not None:
            log_ctx["doc_id"] = doc_id
        if page_num is not None:
            log_ctx["page_num"] = page_num

        if is_blank(image):
            return PageResult(text="", model="")

        # Resize large images to reduce token cost and latency. Copy first so
        # the caller's image is not mutated in-place.
        image = image.copy()
        image.thumbnail((self.settings.OCR_MAX_SIDE, self.settings.OCR_MAX_SIDE))
        payload = _image_to_base64_png(image)

        messages = [
            {"role": "system", "content": TRANSCRIPTION_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{payload}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ]

        models_to_try = unique_models(self.settings.AI_MODELS)
        primary_model = models_to_try[0] if models_to_try else ""

        for model in models_to_try:
            params = {
                "model": model,
                "messages": messages,
                "timeout": self.settings.REQUEST_TIMEOUT,
            }
            try:
                self._stats.inc("attempts")
                response = self._create_completion(**params)
                text = (response.choices[0].message.content or "").strip()

                if is_error_content(text, self.settings.OCR_REFUSAL_MARKERS):
                    log.warning("Model refused to transcribe", model=model, **log_ctx)
                    self._stats.inc("refusals")
                    continue
                if model != primary_model:
                    log.info("Fallback model succeeded", model=model, **log_ctx)
                    self._stats.inc("fallback_successes")
                return PageResult(text=text, model=model)
            except openai.APIError as e:
                log.warning(
                    "API call for model failed after all retries",
                    model=model,
                    error=str(e),
                    **log_ctx,
                )
                self._stats.inc("api_errors")

        log.error("All models failed or refused to transcribe the page", **log_ctx)
        return PageResult(text=self.settings.REFUSAL_MARK, model="")


def _image_to_base64_png(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()
