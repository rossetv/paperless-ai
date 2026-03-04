"""
OCR Provider
============

Abstract base class for OCR providers and the concrete
:class:`OpenAIProvider` implementation.

The provider is responsible for:

1. Preparing a single page image (resize, encode to base64 PNG).
2. Sending it to a vision-capable LLM with the transcription prompt.
3. Trying each model in the configured fallback chain until one succeeds.
4. Detecting refusals and redaction markers.
5. Tracking per-document statistics (attempts, refusals, fallback successes).
"""

import base64
import threading
from abc import ABC, abstractmethod
from io import BytesIO

import openai
import structlog
from PIL import Image

from common.config import Settings
from common.llm import OpenAIChatMixin, unique_models
from common.utils import contains_redacted_marker, is_blank
from .prompts import TRANSCRIPTION_PROMPT

log = structlog.get_logger(__name__)


def is_refusal(text: str, markers: list[str]) -> bool:
    """
    Check whether the model declined to transcribe (case-insensitive).

    Returns ``True`` when *text* contains any of the configured refusal
    *markers* or a bracketed ``[REDACTED …]`` marker.
    """
    text_lower = text.lower()
    return any(marker in text_lower for marker in markers) or contains_redacted_marker(
        text
    )


class OcrProvider(ABC):
    """
    Abstract base class for OCR providers.

    Subclass this to add support for a new vision-capable LLM backend.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def transcribe_image(
        self,
        image: Image.Image,
        doc_id: int | None = None,
        page_num: int | None = None,
    ) -> tuple[str, str]:
        """
        Transcribe an image and return ``(text, model_used)``.

        *doc_id* and *page_num* are optional context fields used for logging.
        """
        raise NotImplementedError


class OpenAIProvider(OpenAIChatMixin, OcrProvider):
    """
    OCR provider backed by the OpenAI (or Ollama-compatible) chat API.

    Tries each model in ``settings.AI_MODELS`` in order, falling back to the
    next model when the current one refuses or errors.
    """

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._stats_lock = threading.Lock()
        self._stats = {
            "attempts": 0,
            "refusals": 0,
            "api_errors": 0,
            "fallback_successes": 0,
        }

    def _inc_stat(self, key: str) -> None:
        """Thread-safe increment of a stats counter."""
        with self._stats_lock:
            self._stats[key] += 1

    def get_stats(self) -> dict:
        """Return a snapshot of OCR model stats for this provider instance."""
        with self._stats_lock:
            return dict(self._stats)

    def transcribe_image(
        self,
        image: Image.Image,
        doc_id: int | None = None,
        page_num: int | None = None,
    ) -> tuple[str, str]:
        """
        Transcribe a single page image using the configured model chain.

        Returns ``("", "")`` for blank pages.  Returns
        ``(settings.REFUSAL_MARK, "")`` when every model refuses or errors.
        """
        log_ctx: dict[str, int] = {}
        if doc_id is not None:
            log_ctx["doc_id"] = doc_id
        if page_num is not None:
            log_ctx["page_num"] = page_num

        if is_blank(image):
            return "", ""

        # Resize large images to reduce token cost and latency
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
                self._inc_stat("attempts")
                response = self._create_completion(**params)
                text = (response.choices[0].message.content or "").strip()

                if not is_refusal(text, self.settings.OCR_REFUSAL_MARKERS):
                    if model != primary_model:
                        log.info("Fallback model succeeded", model=model, **log_ctx)
                        self._inc_stat("fallback_successes")
                    return text, model
                else:
                    log.warning("Model refused to transcribe", model=model, **log_ctx)
                    self._inc_stat("refusals")
            except openai.APIError as e:
                log.warning(
                    "API call for model failed after all retries",
                    model=model,
                    error=e,
                    **log_ctx,
                )
                self._inc_stat("api_errors")

        log.error("All models failed or refused to transcribe the page", **log_ctx)
        return self.settings.REFUSAL_MARK, ""


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _image_to_base64_png(image: Image.Image) -> str:
    """Encode a PIL Image as a base64-encoded PNG string."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


