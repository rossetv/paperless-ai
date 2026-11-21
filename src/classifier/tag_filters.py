"""Tag filtering, deduplication, and enrichment for classification output."""

from __future__ import annotations

import datetime as dt
from typing import Callable, Iterable

import structlog

from .constants import (
    BLACKLISTED_TAGS,
    MODEL_FOOTER_RE,
)
from .metadata import parse_iso_date_prefix
from .normalisers import normalise_name, normalise_simple

log = structlog.get_logger(__name__)


def dedupe_tags(tags: Iterable[str]) -> list[str]:
    """Deduplicate tags case-insensitively, keeping order and dropping blanks.

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
    """Remove tags that duplicate the correspondent, document type, or person.

    The correspondent is compared with company suffixes stripped, so a
    *"Revolut Ltd"* tag is caught when the correspondent is *"Revolut"*.
    """
    correspondent_key = normalise_name(correspondent) if correspondent else ""
    document_type_key = normalise_simple(document_type) if document_type else ""
    person_key = normalise_simple(person) if person else ""

    filtered: list[str] = []
    for tag in dedupe_tags(tags):
        tag_simple = normalise_simple(tag)
        tag_name = normalise_name(tag)
        if correspondent_key and (
            tag_simple == correspondent_key or tag_name == correspondent_key
        ):
            continue
        if document_type_key and tag_simple == document_type_key:
            continue
        if person_key and tag_simple == person_key:
            continue
        filtered.append(tag)
    return filtered


def filter_blacklisted_tags(tags: Iterable[str]) -> list[str]:
    """Remove tags whose normalised form is in :data:`BLACKLISTED_TAGS`.

    >>> filter_blacklisted_tags(["New", "AI", "Bills"])
    ['Bills']
    """
    return [
        tag
        for tag in dedupe_tags(tags)
        if normalise_simple(tag) not in BLACKLISTED_TAGS
    ]


def extract_model_tags(text: str) -> list[str]:
    """Extract model names from every ``Transcribed by model: a, b`` footer.

    Content OCR'd more than once can carry several footers.
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
    *,
    today: Callable[[], dt.date] = dt.date.today,
) -> list[str]:
    """Combine the LLM's tags with the required tags, capping the LLM's at *tag_limit*.

    Required tags (OCR model names, the document year or today's, and
    *default_country_tag*) come first and do not count toward the limit.
    Returns a lowercased, deduplicated list.
    """
    tag_limit = max(0, tag_limit)

    base_tags = dedupe_tags(tags)
    required_tags: list[str] = []

    required_tags.extend(extract_model_tags(text))

    year_tag = _extract_year(document_date) or today().strftime("%Y")
    required_tags.append(year_tag)

    if default_country_tag:
        required_tags.append(default_country_tag)

    required_tags = dedupe_tags(required_tags)
    required_set = {tag.lower() for tag in required_tags}

    # An LLM-suggested tag that duplicates a required one is dropped from the
    # optional set: it is already covered and must not eat into the limit.
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
