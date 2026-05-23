"""Tests for store.reader._filters — the browse-filter SQL helper.

build_browse_where composes the shared SearchFilters fragment with the
optional case-insensitive text predicate the Library browse needs.  Only the
structure of the produced SQL and the parameter list is asserted here — the
full query is exercised by test_reader_browse.py against a real database.
"""

from __future__ import annotations

from store.models import DocumentBrowseQuery
from store.reader._filters import build_browse_where


def _query(**overrides: object) -> DocumentBrowseQuery:
    """Build a DocumentBrowseQuery with all-default (no-restriction) fields."""
    base: dict[str, object] = {
        "text": None,
        "date_from": None,
        "date_to": None,
        "correspondent_id": None,
        "document_type_id": None,
        "tag_ids": (),
        "sort": "created",
        "descending": True,
        "offset": 0,
        "limit": 20,
    }
    base.update(overrides)
    return DocumentBrowseQuery(**base)  # type: ignore[arg-type]


def test_no_filters_yields_empty_clause() -> None:
    """An all-default query produces no WHERE clause and no parameters."""
    where, params = build_browse_where(_query())
    assert where == ""
    assert params == []


def test_correspondent_filter_is_parameterised() -> None:
    """A correspondent filter binds the id, never splices it into the SQL."""
    where, params = build_browse_where(_query(correspondent_id=10))
    assert where.startswith("WHERE ")
    assert "d.correspondent_id = ?" in where
    assert params == [10]


def test_text_predicate_matches_title_correspondent_and_type() -> None:
    """The text predicate ORs title, correspondent name and type name."""
    where, params = build_browse_where(_query(text="gas"))
    assert where.startswith("WHERE ")
    # Three LIKE branches, one per searchable field, all bound.
    # The ESCAPE clause uses a single backslash character as the escape char.
    assert where.count("LIKE ? ESCAPE '\\'") == 3
    assert "d.title" in where
    assert "corr.name" in where
    assert "dtype.name" in where
    # Each branch binds the same wildcard-wrapped term.
    assert params == ["%gas%", "%gas%", "%gas%"]


def test_text_predicate_escapes_like_wildcards() -> None:
    """A user term containing % / _ / backslash is escaped to a literal."""
    where, params = build_browse_where(_query(text="50%_x"))
    # % and _ and \\ are escaped with a leading backslash so LIKE treats
    # them literally; the term is then wrapped in % wildcards.
    assert params == [r"%50\%\_x%", r"%50\%\_x%", r"%50\%\_x%"]


def test_text_and_filters_combine_with_and() -> None:
    """A text query and a correspondent filter are joined by AND."""
    where, params = build_browse_where(
        _query(text="bill", correspondent_id=5)
    )
    assert where.startswith("WHERE ")
    assert " AND " in where
    assert params == [5, "%bill%", "%bill%", "%bill%"]


def test_empty_text_is_treated_as_no_restriction() -> None:
    """An empty-string text query adds no predicate."""
    where, params = build_browse_where(_query(text=""))
    assert where == ""
    assert params == []
