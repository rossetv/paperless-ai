"""Metadata validation and transformation for classification output."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable

import structlog

from common.paperless import PaperlessCustomField
from .result import ClassificationResult

log = structlog.get_logger(__name__)

# Splits locale strings like "en-US" or "pt_BR".
_LOCALE_SEP_RE: re.Pattern[str] = re.compile(r"[-_]")


def parse_iso_date_prefix(value: str | None) -> dt.date | None:
    """Parse an ISO-8601 date string, stripping any ``T`` time suffix.

    Returns ``None`` when *value* is ``None``, empty, or unparseable.
    """
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip().split("T")[0])
    except ValueError:
        return None


_DATE_FLOOR = dt.date(1900, 1, 1)
# Reject dates more than ~366 days in the future; injected/hallucinated dates
# tend to be absurdly far out (e.g. "9999-12-31") rather than slightly future.
_DATE_FUTURE_DAYS = 366


def parse_document_date(value: str) -> str | None:
    """Validate an ISO-8601 date string and normalise it to ``YYYY-MM-DD``.

    Returns ``None`` when it is empty, unparseable, or outside 1900-01-01 to
    366 days ahead. Out-of-window dates are logged so operators can spot
    prompt injection or hallucination.
    """
    parsed = parse_iso_date_prefix(value)
    if parsed is None:
        if value:
            log.warning("classification.invalid_date", value=value)
        return None
    today = dt.date.today()
    ceiling = today + dt.timedelta(days=_DATE_FUTURE_DAYS)
    if parsed < _DATE_FLOOR or parsed > ceiling:
        log.warning(
            "classification.implausible_date",
            value=value,
            floor=_DATE_FLOOR.isoformat(),
            ceiling=ceiling.isoformat(),
        )
        return None
    return parsed.isoformat()


def resolve_date_for_tags(
    result_date: str | None,
    existing_date: str | None,
    *,
    today: Callable[[], dt.date] = dt.date.today,
) -> str:
    """Pick the date for year-tag derivation.

    Prefers *result_date*, then *existing_date* (Paperless ``created``), then
    *today()*.
    """
    for value in (result_date, existing_date):
        parsed = parse_iso_date_prefix(value)
        if parsed is not None:
            return parsed.isoformat()
    return today().isoformat()


def normalise_language(language: str) -> str | None:
    """Coerce a language string to an ISO-639-1 code or ``"und"``.

    Accepts bare codes (``"en"``) and locales (``"en-US"``). Returns ``None``
    for empty input, meaning leave the field unchanged.
    """
    if not language:
        return None
    language = language.strip().lower()
    if language == "und":
        return language
    if len(language) == 2 and language.isalpha():
        return language
    if "-" in language or "_" in language:
        prefix = _LOCALE_SEP_RE.split(language, maxsplit=1)[0]
        if len(prefix) == 2 and prefix.isalpha():
            return prefix
    return "und"


def update_custom_fields(
    existing: list[PaperlessCustomField] | None,
    field_id: int,
    value: str,
) -> list[PaperlessCustomField]:
    """Return a copy of *existing* with the *field_id* value set (upserted)."""
    existing = existing or []
    updated: list[PaperlessCustomField] = []
    found = False
    for field in existing:
        if field.get("field") == field_id:
            updated.append({"field": field_id, "value": value})
            found = True
        else:
            updated.append(field)
    if not found:
        updated.append({"field": field_id, "value": value})
    return updated


def is_empty_classification(result: ClassificationResult) -> bool:
    """Return ``True`` if every field and tag of *result* is blank."""
    if result.tags and any(tag.strip() for tag in result.tags):
        return False
    fields = [
        result.title,
        result.correspondent,
        result.document_type,
        result.document_date,
        result.language,
        result.person,
    ]
    return not any((field or "").strip() for field in fields)
