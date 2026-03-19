"""Startup preflight checks for Paperless-ngx and LLM provider reachability."""

from __future__ import annotations

from openai import APIError as OpenAIAPIError
import structlog

from .config import Settings
from .llm import get_openai_client, is_openai_client_ready
from .paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient

log = structlog.get_logger(__name__)


class PreflightError(RuntimeError):
    """Raised when a fatal preflight check fails."""


def run_preflight_checks(settings: Settings, client: PaperlessClient) -> None:
    """Run all preflight checks.  Raises :class:`PreflightError` on fatal failure."""
    _check_paperless_reachable(settings, client)
    _check_tag_ids_exist(settings, client)
    _check_llm_reachable()


def _check_paperless_reachable(settings: Settings, client: PaperlessClient) -> None:
    """Verify that the Paperless-ngx API is reachable (single fast request, no retry)."""
    try:
        client.ping(timeout=10)
        log.info("Preflight: Paperless-ngx API is reachable", url=settings.PAPERLESS_URL)
    except PAPERLESS_CALL_EXCEPTIONS as exc:
        raise PreflightError(
            f"Paperless-ngx API is not reachable at {settings.PAPERLESS_URL}: {exc}"
        ) from exc


def _check_tag_ids_exist(settings: Settings, client: PaperlessClient) -> None:
    try:
        all_tags = client.list_tags()
    except PAPERLESS_CALL_EXCEPTIONS:
        log.warning("Preflight: Could not fetch tags from Paperless; skipping tag validation")
        return

    existing_ids = {tag["id"] for tag in all_tags if "id" in tag}

    tag_configs = [
        ("PRE_TAG_ID", settings.PRE_TAG_ID),
        ("POST_TAG_ID", settings.POST_TAG_ID),
        ("OCR_PROCESSING_TAG_ID", settings.OCR_PROCESSING_TAG_ID),
        ("CLASSIFY_PRE_TAG_ID", settings.CLASSIFY_PRE_TAG_ID),
        ("CLASSIFY_POST_TAG_ID", settings.CLASSIFY_POST_TAG_ID),
        ("CLASSIFY_PROCESSING_TAG_ID", settings.CLASSIFY_PROCESSING_TAG_ID),
        ("ERROR_TAG_ID", settings.ERROR_TAG_ID),
    ]

    for name, tag_id in tag_configs:
        if tag_id is None:
            continue
        if tag_id not in existing_ids:
            log.warning(
                "Preflight: Configured tag ID does not exist in Paperless",
                setting=name,
                tag_id=tag_id,
            )
        else:
            log.debug("Preflight: Tag ID verified", setting=name, tag_id=tag_id)


def _check_llm_reachable() -> None:
    """Best-effort check that the LLM provider is reachable."""
    if not is_openai_client_ready():
        log.warning("Preflight: OpenAI client not initialised; skipping LLM check")
        return
    try:
        client = get_openai_client()
        client.models.list()
        log.info("Preflight: LLM provider is reachable")
    except (OpenAIAPIError, OSError) as exc:
        log.warning(
            "Preflight: LLM provider is not reachable; "
            "the daemon will retry when processing documents",
            error=str(exc),
        )
