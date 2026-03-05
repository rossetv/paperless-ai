"""Metadata validation and transformation for classification output."""

from __future__ import annotations

import datetime as dt
import re

import structlog

from .result import ClassificationResult

log = structlog.get_logger(__name__)

# Splits locale-style strings like "en-US" or "pt_BR" on the separator.
_LOCALE_SEP_RE: re.Pattern[str] = re.compile(r"[-_]")


def parse_document_date(value: str) -> str | None:
    """
    Validate and normalize a date string to ``YYYY-MM-DD``.

    Accepts ISO-8601 date strings (optionally with a ``T`` time component).
    Returns ``None`` when the value is empty or unparseable.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return dt.date.fromisoformat(value.split("T")[0]).isoformat()
    except ValueError:
        log.warning("Invalid document_date from classifier", value=value)
        return None


def resolve_date_for_tags(
    result_date: str | None,
    existing_date: str | None,
) -> str:
    """
    Pick the best available date for year-tag derivation.

    Prefers the classifier's *result_date*, falls back to the document's
    *existing_date* (the ``created`` field in Paperless), and finally uses
    today's date.
    """
    for value in (result_date, existing_date):
        if not value:
            continue
        try:
            return dt.date.fromisoformat(value.split("T")[0]).isoformat()
        except ValueError:
            log.debug("Skipping unparseable date candidate", value=value)
            continue
    return dt.date.today().isoformat()


def normalize_language(language: str) -> str | None:
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
    existing: list[dict] | None,
    field_id: int,
    value: str,
) -> list[dict]:
    """
    Upsert a Paperless custom-field value in the existing list.

    If a field with *field_id* already exists it is replaced; otherwise a new
    entry is appended.  The original list is not mutated.
    """
    existing = existing or []
    updated: list[dict] = []
    found = False
    for item in existing:
        if item.get("field") == field_id:
            updated.append({"field": field_id, "value": value})
            found = True
        else:
            updated.append(item)
    if not found:
        updated.append({"field": field_id, "value": value})
    return updated


def is_empty_classification(result: ClassificationResult) -> bool:
    """
    Return ``True`` if the classification result contains no usable fields.

    A result is "empty" when every scalar field is blank and the tag list
    contains no non-whitespace entries.
    """
    if result.tags and any(
        tag.strip() for tag in result.tags if isinstance(tag, str)
    ):
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
