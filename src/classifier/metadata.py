"""Metadata validation and transformation for classification output."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable

import structlog

from common.paperless import PaperlessCustomField
from .result import ClassificationResult

log = structlog.get_logger(__name__)

# Splits locale-style strings like "en-US" or "pt_BR" on the separator.
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
    """
    Validate and normalise a date string to ``YYYY-MM-DD``.

    Accepts ISO-8601 date strings (optionally with a ``T`` time component).
    Returns ``None`` when the value is empty, unparseable, or outside the
    plausibility window (before 1900-01-01 or more than 366 days in the
    future).  Out-of-window dates are logged as a warning so operators can
    spot prompt-injection or hallucination.
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
    """
    Pick the best available date for year-tag derivation.

    Prefers the classifier's *result_date*, falls back to the document's
    *existing_date* (the ``created`` field in Paperless), and finally uses
    today's date.

    Args:
        today: The current-date source for the final fallback. Defaults to
            :func:`datetime.date.today`; tests inject a fixed date so the
            fallback is deterministic (CODE_GUIDELINES §11.4).
    """
    for value in (result_date, existing_date):
        parsed = parse_iso_date_prefix(value)
        if parsed is not None:
            return parsed.isoformat()
    return today().isoformat()


def normalise_language(language: str) -> str | None:
    """
    Coerce a language string to an ISO-639-1 two-letter code or ``"und"``.

    Handles bare codes (``"en"``), locale-style strings (``"en-US"``), and
    the special undetermined code (``"und"``).  Returns ``None`` when the
    input is empty, which tells the caller to leave the field unchanged.
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
    """
    Upsert a Paperless custom-field value in the existing list.

    If a field with *field_id* already exists it is replaced; otherwise a new
    entry is appended.  The original list is not mutated.
    """
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
    """
    Return ``True`` if the classification result contains no usable fields.

    A result is "empty" when every scalar field is blank and the tag list
    contains no non-whitespace entries.
    """
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
