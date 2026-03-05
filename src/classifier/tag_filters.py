"""Tag filtering, deduplication, and enrichment for classification output."""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import structlog

from .constants import (
    BLACKLISTED_TAGS,
    MODEL_FOOTER_RE,
)
from .metadata import parse_iso_date_prefix
from .normalizers import normalize_name, normalize_simple

log = structlog.get_logger(__name__)


def dedupe_tags(tags: Iterable[str]) -> list[str]:
    """
    Deduplicate tags while preserving insertion order (case-insensitive).

    Whitespace-only and empty strings are silently dropped.

    >>> dedupe_tags(["Bills", "bills", " BILLS ", "Payslip"])
    ['Bills', 'Payslip']
    """
    seen: set[str] = set()
    output: list[str] = []
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output


def filter_redundant_tags(
    tags: Iterable[str],
    correspondent: str,
    document_type: str,
    person: str,
) -> list[str]:
    """
    Remove tags that duplicate the correspondent, document type, or person.

    Comparison uses :func:`normalize_simple` for document-type/person and
    :func:`normalize_name` (which strips company suffixes) for the
    correspondent, so *"Revolut Ltd"* as a tag is caught when the
    correspondent is *"Revolut"*.
    """
    correspondent_key = normalize_name(correspondent) if correspondent else ""
    document_type_key = normalize_simple(document_type) if document_type else ""
    person_key = normalize_simple(person) if person else ""

    filtered: list[str] = []
    for tag in dedupe_tags(tags):
        tag_simple = normalize_simple(tag)
        tag_name = normalize_name(tag)
        if correspondent_key and (tag_simple == correspondent_key or tag_name == correspondent_key):
            continue
        if document_type_key and tag_simple == document_type_key:
            continue
        if person_key and tag_simple == person_key:
            continue
        filtered.append(tag)
    return filtered


def filter_blacklisted_tags(tags: Iterable[str]) -> list[str]:
    """
    Remove tags whose normalized form is in :data:`BLACKLISTED_TAGS`.

    >>> filter_blacklisted_tags(["New", "AI", "Bills"])
    ['Bills']
    """
    return [
        tag for tag in dedupe_tags(tags)
        if normalize_simple(tag) not in BLACKLISTED_TAGS
    ]


def extract_model_tags(text: str) -> list[str]:
    """
    Extract model name tags from ``Transcribed by model: …`` footers.

    The OCR daemon appends a footer like::

        Transcribed by model: gpt-5-mini, o4-mini

    This function parses all such footers (there may be more than one in
    multi-run content) and returns a deduplicated list of model names.
    """
    matches = list(MODEL_FOOTER_RE.finditer(text))
    if not matches:
        return []
    tags: list[str] = []
    for match in matches:
        value = match.group(1).splitlines()[0]
        for token in value.split(","):
            tag = token.strip()
            if tag:
                tags.append(tag)
    return dedupe_tags(tags)


def enrich_tags(
    tags: list[str],
    text: str,
    document_date: str,
    default_country_tag: str,
    tag_limit: int,
) -> list[str]:
    """
    Combine model-suggested tags with required tags and enforce the limit.

    **Required tags** (always included, not counted toward *tag_limit*):
    - OCR model markers extracted from the text footer.
    - A year tag derived from *document_date* (falls back to the current year).
    - The *default_country_tag* if configured.

    **Optional tags** (the LLM's suggestions minus required ones):
    - Capped to *tag_limit*.

    Returns a lowercased, deduplicated list with required tags first.
    """
    tag_limit = max(0, tag_limit)

    base_tags = dedupe_tags(tags)
    required_tags: list[str] = []

    # Model markers
    required_tags.extend(extract_model_tags(text))

    # Year tag
    year_tag = _extract_year(document_date) or dt.date.today().strftime("%Y")
    required_tags.append(year_tag)

    # Country tag
    if default_country_tag:
        required_tags.append(default_country_tag)

    required_tags = dedupe_tags(required_tags)
    required_set = {tag.lower() for tag in required_tags}

    # Split base tags into required (already covered) and optional
    non_required = [tag for tag in base_tags if tag.lower() not in required_set]
    trimmed = non_required[:tag_limit] if tag_limit else []

    if len(non_required) > len(trimmed):
        log.warning(
            "Trimmed non-required tags to limit",
            tag_limit=tag_limit,
            before=len(non_required),
            after=len(trimmed),
        )

    combined = dedupe_tags(required_tags + trimmed)
    return [tag.lower() for tag in combined]


def _extract_year(value: str) -> str | None:
    """Extract a YYYY year string from an ISO-8601 date (or prefix)."""
    parsed = parse_iso_date_prefix(value)
    return parsed.strftime("%Y") if parsed is not None else None
