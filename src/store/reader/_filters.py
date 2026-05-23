"""SQL filter helpers private to the reader.

Builds the parameterised ``WHERE`` fragment shared by ``vector_search`` and
``keyword_search`` (:func:`build_filters`), escapes a single FTS5 search term
(:func:`escape_fts_term`), and builds the ``WHERE`` fragment for the Library
browse list (:func:`build_browse_where`).  Every value is bound through
parameter substitution; only ``?`` placeholders and fixed SQL keywords are
ever interpolated (CODE_GUIDELINES §9.5).
"""

from __future__ import annotations

from store.models import DocumentBrowseQuery, SearchFilters


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
        clauses.append("EXISTS (SELECT 1 FROM json_each(d.tag_ids) WHERE value = ?)")
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


# The character used to escape LIKE metacharacters in the browse text match.
# Bound into the SQL via ``ESCAPE '\'`` so a literal ``%`` / ``_`` typed by
# the user is matched verbatim rather than acting as a wildcard.
_LIKE_ESCAPE = "\\"


def _escape_like_term(term: str) -> str:
    """Escape LIKE metacharacters in *term* so it matches literally.

    ``%``, ``_`` and the escape character itself are each prefixed with the
    escape character.  The result is intended to be wrapped in ``%`` wildcards
    and bound to a ``LIKE ? ESCAPE '\\'`` predicate.  The backslash is escaped
    first so the escapes added for ``%`` / ``_`` are not themselves re-escaped.
    """
    escaped = term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE + _LIKE_ESCAPE)
    escaped = escaped.replace("%", _LIKE_ESCAPE + "%")
    return escaped.replace("_", _LIKE_ESCAPE + "_")


def build_browse_where(
    query: DocumentBrowseQuery,
) -> tuple[str, list[str | int]]:
    """Build the SQL WHERE clause and parameters for a Library browse query.

    Reuses :func:`build_filters` for the correspondent / document-type /
    tags / date-range predicates — :class:`~store.models.DocumentBrowseQuery`
    shares those five fields with :class:`~store.models.SearchFilters` by
    design — and adds the optional case-insensitive text predicate.

    The text predicate matches when the search text appears as a substring of
    **any** of: the document title (``d.title``), the joined correspondent
    name (``corr.name``), or the joined document-type name (``dtype.name``).
    The caller's SQL must therefore ``LEFT JOIN taxonomy`` under the aliases
    ``corr`` and ``dtype``.  Matching is via SQLite ``LIKE``, case-insensitive
    for ASCII; the term is escaped (:func:`_escape_like_term`) and wrapped in
    ``%`` wildcards so user-typed metacharacters match literally.

    Returns a tuple of ``(where_clause, params)``.  When no filter is active
    the clause is the empty string; otherwise it starts with ``WHERE``.  The
    clause contains only fixed SQL and ``?`` placeholders — every value is in
    *params*, bound by parameter substitution (CODE_GUIDELINES §9.5).
    """
    # Reuse the shared filter fragment for the five common fields.
    shared = SearchFilters(
        date_from=query.date_from,
        date_to=query.date_to,
        correspondent_id=query.correspondent_id,
        document_type_id=query.document_type_id,
        tag_ids=query.tag_ids,
    )
    base_clause, params = build_filters(shared)

    clauses: list[str] = []
    # build_filters returns either "" or a "WHERE ..."-prefixed string; strip
    # the keyword so this function can re-assemble one WHERE for everything.
    if base_clause:
        clauses.append(base_clause.removeprefix("WHERE "))

    if query.text:
        like_term = f"%{_escape_like_term(query.text)}%"
        # OR across the three searchable fields; each branch binds the term.
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
