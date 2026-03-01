"""
Third-party library configuration.

This module isolates all side-effectful library setup (OpenAI SDK, Pillow,
httpx) behind a single ``setup_libraries`` entry point.  It is intentionally
kept free of business-logic imports so that it can be reused by any daemon,
CLI tool, or test harness that needs the same library configuration.

Typical usage::

    from common.config import Settings
    from common.library_setup import setup_libraries

    settings = Settings()
    setup_libraries(settings)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import openai
from PIL import Image

if TYPE_CHECKING:
    from common.config import Settings


def setup_libraries(settings: Settings) -> None:
    """Configure third-party libraries based on application settings.

    Performs the following:

    1. **Pillow** — disables the ``MAX_IMAGE_PIXELS`` safety limit so that
       high-DPI scans are not rejected.
    2. **httpx / OpenAI** — creates a trust-env-disabled ``httpx.Client``
       to avoid proxy variables leaking into SDK calls, then configures the
       ``openai`` module-level client (base URL, API key, HTTP client).

    Args:
        settings: A fully-initialised :class:`~common.config.Settings` instance.
            Only ``LLM_PROVIDER``, ``OLLAMA_BASE_URL``, and ``OPENAI_API_KEY``
            are read.
    """
    # Allow arbitrarily large images (high-DPI document scans).
    Image.MAX_IMAGE_PIXELS = None

    # OpenAI's SDK uses httpx internally.  In container environments it is
    # common to have proxy env-vars set unintentionally; explicitly opting
    # out of environment-based trust avoids surprising behaviour.
    http_client = httpx.Client(trust_env=False)

    if settings.LLM_PROVIDER == "ollama":
        openai.base_url = settings.OLLAMA_BASE_URL
        openai.api_key = "dummy"
    else:
        openai.api_key = settings.OPENAI_API_KEY

    openai.http_client = http_client
