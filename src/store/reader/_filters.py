"""Parameterised ``WHERE`` builders and FTS5/LIKE escaping for the reader.

Only fixed SQL and ``?`` placeholders are interpolated; every value is bound.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta

from store.models import DocumentBrowseQuery, SearchFilters


def build_filters(filters: SearchFilters) -> tuple[str, list[str | int]]:
    """Return ``(where_clause, params)`` for *filters*; ``""`` when none is set.

    ``d.created`` holds full ISO-8601 timestamps, which compare correctly
    against bare ``YYYY-MM-DD`` bounds as strings. The upper bound is the
    half-open ``< date_to + 1 day`` because wrapping the column in ``date()``
    would stop ``idx_documents_created`` being used.
    """
    clauses: list[str] = []
    params: list[str | int] = []

    lower = _lower_bound(filters.date_from) if filters.date_from is not None else None
    if lower is not None:
        clauses.append("d.created >= ?")
        params.append(lower)

    if filters.date_to is not None:
        exclusive_upper = _exclusive_upper_bound(filters.date_to)
        if exclusive_upper is not None:
            clauses.append("d.created < ?")
            params.append(exclusive_upper)

    if filters.correspondent_id is not None:
        clauses.append("d.correspondent_id = ?")
        params.append(filters.correspondent_id)

    if filters.document_type_id is not None:
        clauses.append("d.document_type_id = ?")
        params.append(filters.document_type_id)

    for tag_id in filters.tag_ids:
        clauses.append("EXISTS (SELECT 1 FROM json_each(d.tag_ids) WHERE value = ?)")
        params.append(tag_id)

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def _lower_bound(date_from: str) -> str | None:
    """Return the bare ``YYYY-MM-DD`` of an inclusive ``date_from``, or ``None``.

    Handled like ``date_to``: only the leading day is used, so a timestamp does
    not skip documents created at midnight, and an unparseable value is dropped.
    """
    try:
        return date.fromisoformat(date_from[:10]).isoformat()
    except ValueError:
        return None


def _exclusive_upper_bound(date_to: str) -> str | None:
    """Return the half-open ``< bound`` for an inclusive ``date_to`` day.

    *date_to* comes verbatim from a UI query param or the LLM planner, so it
    may be a full timestamp or garbage. Only its leading ``YYYY-MM-DD`` is used;
    an unparseable value returns ``None`` and the bound is dropped rather than
    failing the search.
    """
    try:
        day = date.fromisoformat(date_to[:10])
    except ValueError:
        return None
    return str(day + timedelta(days=1))


def escape_fts_term(term: str) -> str:
    """Escape a single FTS5 search term by doubling embedded double-quotes.

    The caller wraps each escaped term in double-quotes, so ``foo OR bar``
    becomes a literal phrase and FTS5 operators are neutralised. Never pass a
    pre-built MATCH expression as one term: it would be quoted into a phrase.
    """
    return term.replace('"', '""')


# Paired with ``ESCAPE '\'`` in the SQL so a typed ``%`` or ``_`` matches literally.
_LIKE_ESCAPE = "\\"


def _escape_like_term(term: str) -> str:
    """Escape LIKE metacharacters in *term* so it matches literally.

    The backslash is escaped first so the escapes added for ``%`` and ``_`` are
    not themselves re-escaped.
    """
    escaped = term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE + _LIKE_ESCAPE)
    escaped = escaped.replace("%", _LIKE_ESCAPE + "%")
    return escaped.replace("_", _LIKE_ESCAPE + "_")


def build_browse_where(
    query: DocumentBrowseQuery,
) -> tuple[str, list[str | int]]:
    """Return ``(where_clause, params)`` for a Library browse query.

    Adds to :func:`build_filters` a text match on the title, correspondent or
    document type, so the caller's SQL must ``LEFT JOIN taxonomy`` as ``corr``
    and ``dtype``. SQLite ``LIKE`` is case-insensitive for ASCII only.
    """
    shared = SearchFilters(
        date_from=query.date_from,
        date_to=query.date_to,
        correspondent_id=query.correspondent_id,
        document_type_id=query.document_type_id,
        tag_ids=query.tag_ids,
    )
    base_clause, params = build_filters(shared)

    clauses: list[str] = []
    if base_clause:
        clauses.append(base_clause.removeprefix("WHERE "))

    if query.text:
        like_term = f"%{_escape_like_term(query.text)}%"
        clauses.append(
            "("
            "d.title LIKE ? ESCAPE '\\' "
            "OR corr.name LIKE ? ESCAPE '\\' "
            "OR dtype.name LIKE ? ESCAPE '\\'"
            ")"
        )
        params.extend([like_term, like_term, like_term])

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


# Bounds the MATCH expression; the AND of more terms than this adds cost, not precision.
MAX_FTS_TERMS = 64


def _token_key(term: str) -> tuple[str, ...]:
    """Return what the FTS5 default tokenizer would index *term* as, conservatively.

    ``chunks_fts`` uses the default ``unicode61`` tokenizer: it lower-cases and
    splits on every character that is not a letter or number. The tokenizer folds
    diacritics (``café`` is indexed as ``cafe``), but this key does not, so terms
    that differ only by an accent keep separate keys. Combining marks stay inside
    a token.
    """
    tokens: list[str] = []
    current: list[str] = []
    for char in term.lower():
        if char.isalnum() or unicodedata.category(char).startswith("M"):
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def build_match_expr(terms: Sequence[str]) -> str:
    """AND-combine *terms* into a quoted FTS5 MATCH expression.

    Terms the tokenizer treats identically (case and punctuation variants) are
    dropped, first spelling wins, and at most :data:`MAX_FTS_TERMS` distinct
    terms are kept. A term with no letter or digit indexes nothing, so quoting it
    would make the AND match no document: it is dropped. When no term is left the
    expression is the empty phrase ``""``, which matches nothing and is valid FTS5.
    """
    distinct: dict[tuple[str, ...], str] = {}
    for term in terms:
        if any(char.isalnum() for char in term):
            distinct.setdefault(_token_key(term), term)
    kept = list(distinct.values())[:MAX_FTS_TERMS]
    if not kept:
        return '""'
    return " AND ".join(f'"{escape_fts_term(term)}"' for term in kept)
