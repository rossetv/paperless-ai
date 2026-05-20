"""SQL filter helpers private to the ranked-retrieval reader.

Builds the parameterised ``WHERE`` fragment shared by ``vector_search`` and
``keyword_search``, and escapes a single FTS5 search term.  Every value is
bound through parameter substitution; only ``?`` placeholders and fixed SQL
keywords are ever interpolated (CODE_GUIDELINES §9.5).
"""

from __future__ import annotations

from store.models import SearchFilters


def build_filters(filters: SearchFilters) -> tuple[str, list[str | int]]:
    """Build the SQL WHERE clause and parameter list for *filters*.

    Returns a tuple of ``(where_clause, params)``.  When no filter is active
    the clause is the empty string; otherwise it starts with the ``WHERE``
    keyword.  The clause contains only fixed SQL and ``?`` placeholders — every
    filter value is in *params*, bound by parameter substitution.

    Filter semantics:

    - ``date_from`` / ``date_to``: inclusive range on ``d.created`` using
      lexicographic ISO-8601 string comparison (normalised dates sort correctly).
    - ``correspondent_id``: equality on ``d.correspondent_id``.
    - ``document_type_id``: equality on ``d.document_type_id``.
    - ``tag_ids``: each id in the tuple must appear as a value in
      ``d.tag_ids``, which is stored as a JSON array.  The membership test
      uses ``json_each(d.tag_ids)``, which requires valid JSON — the writer
      serialises tag_ids with ``json.dumps(list(meta.tag_ids))`` (see
      store/writer.py:upsert_document), so all stored values are valid JSON
      arrays and ``json_each`` works correctly.
    """
    clauses: list[str] = []
    params: list[str | int] = []

    if filters.date_from is not None:
        clauses.append("d.created >= ?")
        params.append(filters.date_from)

    if filters.date_to is not None:
        clauses.append("d.created <= ?")
        params.append(filters.date_to)

    if filters.correspondent_id is not None:
        clauses.append("d.correspondent_id = ?")
        params.append(filters.correspondent_id)

    if filters.document_type_id is not None:
        clauses.append("d.document_type_id = ?")
        params.append(filters.document_type_id)

    for tag_id in filters.tag_ids:
        # Each tag_id must appear in the JSON array stored in d.tag_ids.
        # json_each() expands the array into rows; EXISTS ensures the document
        # is only returned if the given id is present.
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(d.tag_ids) WHERE value = ?)"
        )
        params.append(tag_id)

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def escape_fts_term(term: str) -> str:
    """Escape a single FTS5 search term by doubling embedded double-quotes.

    The term is placed between double-quotes in the MATCH expression so that
    FTS5 treats it as a phrase/token rather than a boolean operator.  Any
    literal double-quote inside the term is doubled per the FTS5 spec.
    """
    return term.replace('"', '""')
