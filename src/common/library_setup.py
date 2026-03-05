"""One-shot third-party library configuration (OpenAI SDK, Pillow, httpx)."""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING

import httpx
import openai
from PIL import Image

if TYPE_CHECKING:
    from common.config import Settings


def setup_libraries(settings: Settings) -> None:
    """Configure Pillow, httpx, and OpenAI SDK from application settings."""
    # Allow arbitrarily large images (high-DPI document scans).
    Image.MAX_IMAGE_PIXELS = None

    # OpenAI's SDK uses httpx internally.  In container environments it is
    # common to have proxy env-vars set unintentionally; explicitly opting
    # out of environment-based trust avoids surprising behaviour.
    http_client = httpx.Client(trust_env=False)
    atexit.register(http_client.close)

    if settings.LLM_PROVIDER == "ollama":
        openai.base_url = settings.OLLAMA_BASE_URL
        openai.api_key = "dummy"
    else:
        openai.api_key = settings.OPENAI_API_KEY

    openai.http_client = http_client
