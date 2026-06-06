"""Shared text-length constants for the search pipeline.

The pipeline truncates a few strings before they go into a structured log
event — a query, a synthesiser adjustment hint — so a log line stays a sane
length.  The planner, the synthesiser, and the core all do this; the cap
literals live here once rather than being respelled at each call site
(``CODE_GUIDELINES.md`` §3.5).

It also owns the RAG-08 ``is_trivial_query`` predicate — the query-shape test
the core uses to decide whether a query is plain enough to skip the planner
LLM call — kept here as the natural home for query-text helpers.

Depends on: standard library only.
"""

from __future__ import annotations

import re

# Maximum characters of a raw user query included in a structured log event.
# A query is logged for triage, not stored — ~60 chars identifies it without
# bloating the log line or risking a very long line in a JSON sink.
QUERY_LOG_PREFIX_CHARS = 60

# Maximum characters of a synthesiser adjustment hint included in a log event.
# An adjustment is a short instruction phrase; 120 chars captures it whole in
# the common case while still bounding a pathological one.
ADJUSTMENT_LOG_PREFIX_CHARS = 120


# RAG-08: a query is "trivial" — worth skipping the planner LLM for — only when
# it is short AND carries no temporal or entity signal the planner would help
# with. Conservative by design: any doubt returns False and the planner runs.
_TRIVIAL_QUERY_MAX_WORDS = 3

# Relative-date and temporal words that imply the planner should derive a date
# filter — their presence makes a query non-trivial.
_TEMPORAL_WORDS = frozenset(
    {
        "last",
        "since",
        "ago",
        "year",
        "years",
        "month",
        "months",
        "week",
        "weeks",
        "day",
        "days",
        "yesterday",
        "today",
        "recent",
        "past",
        "before",
        "after",
        "during",
        "between",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)

# Punctuation that signals an identifier / reference / handle the planner would
# lift into keyword_terms — its presence makes a query non-trivial.
_ENTITY_PUNCTUATION = re.compile(r"[@#/£$€%]")


def is_trivial_query(query: str) -> bool:
    """Return whether *query* is a short, signal-free keyword lookup (RAG-08).

    Trivial = at most ``_TRIVIAL_QUERY_MAX_WORDS`` words AND no digit, no
    temporal word, no identifier punctuation, and no proper-noun token beyond
    the first word (an interior capitalised word suggests an entity the planner
    would resolve). When trivial, the caller may skip the planner LLM call and
    build the fallback-shaped plan directly — retrieval still runs vector + FTS
    on the raw query, so nothing is lost (spec §4.6).

    Args:
        query: The raw user search query.

    Returns:
        True only when the query is safe to short-circuit; False on any doubt.
    """
    words = query.split()
    if not words or len(words) > _TRIVIAL_QUERY_MAX_WORDS:
        return False
    if any(character.isdigit() for character in query):
        return False
    if _ENTITY_PUNCTUATION.search(query):
        return False
    if any(word.casefold() in _TEMPORAL_WORDS for word in words):
        return False
    # A capitalised token after the first word suggests a proper noun (entity).
    for word in words[1:]:
        if word[:1].isupper():
            return False
    return True
