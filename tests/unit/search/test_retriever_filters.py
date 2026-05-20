"""Tests for search.retriever.resolve_filters — free-text filter resolution.

Verifies:
- resolve_filters resolves an exact taxonomy name match.
- resolve_filters resolves a near-match after punctuation/case normalisation.
- resolve_filters drops an unresolvable candidate (it never guesses an id).
- Date candidates pass through unchanged regardless of taxonomy resolution.
- UI filters (ui_filters) override planner candidates entirely.

The RRF fusion and the ``retrieve()`` entry point are covered in
:mod:`test_retriever` (split for the 500-line ceiling, §3.1).
"""

from __future__ import annotations

from search.retriever import resolve_filters
from store.reader import SearchFilters
from tests.helpers.factories import make_facet_set, make_filter_candidates
from tests.helpers.factories import make_taxonomy_entry as _entry


# ---------------------------------------------------------------------------
# resolve_filters — exact match
# ---------------------------------------------------------------------------


def test_resolve_filters_exact_correspondent_match() -> None:
    """resolve_filters resolves a correspondent candidate by exact name."""
    candidates = make_filter_candidates(correspondent="ACME Corp")
    facets = make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=7, name="ACME Corp"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7


def test_resolve_filters_exact_document_type_match() -> None:
    """resolve_filters resolves a document_type candidate by exact name."""
    candidates = make_filter_candidates(document_type="Invoice")
    facets = make_facet_set(
        document_types=(_entry(kind="document_type", entry_id=3, name="Invoice"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.document_type_id == 3


def test_resolve_filters_exact_tag_match() -> None:
    """resolve_filters resolves a tag candidate by exact name."""
    candidates = make_filter_candidates(tags=("important",))
    facets = make_facet_set(
        tags=(_entry(kind="tag", entry_id=5, name="important"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.tag_ids == (5,)


# ---------------------------------------------------------------------------
# resolve_filters — normalised near-match
# ---------------------------------------------------------------------------


def test_resolve_filters_normalised_case_match() -> None:
    """resolve_filters resolves a candidate after case normalisation."""
    candidates = make_filter_candidates(correspondent="acme corp")
    facets = make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=7, name="ACME Corp"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7


def test_resolve_filters_normalised_punctuation_match() -> None:
    """resolve_filters resolves a candidate after stripping punctuation."""
    candidates = make_filter_candidates(correspondent="npower")
    facets = make_facet_set(
        # The taxonomy has "npower." with a trailing period.
        correspondents=(_entry(kind="correspondent", entry_id=12, name="npower."),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 12


def test_resolve_filters_normalised_case_and_punctuation_match() -> None:
    """resolve_filters resolves after both case folding and punctuation removal."""
    candidates = make_filter_candidates(document_type="gas bill")
    facets = make_facet_set(
        document_types=(_entry(kind="document_type", entry_id=9, name="Gas-Bill"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.document_type_id == 9


# ---------------------------------------------------------------------------
# resolve_filters — unresolvable candidate is dropped
# ---------------------------------------------------------------------------


def test_resolve_filters_drops_unresolvable_candidate() -> None:
    """resolve_filters drops a correspondent that matches nothing in the taxonomy."""
    candidates = make_filter_candidates(correspondent="NonExistentCorp")
    facets = make_facet_set(
        correspondents=(
            _entry(kind="correspondent", entry_id=1, name="Some Other Corp"),
        )
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    # Must be None — not guessed to a wrong id.
    assert filters.correspondent_id is None


def test_resolve_filters_drops_unresolvable_tag() -> None:
    """resolve_filters drops a tag that matches nothing; resolves the ones that do."""
    candidates = make_filter_candidates(tags=("real-tag", "ghost-tag"))
    facets = make_facet_set(
        tags=(_entry(kind="tag", entry_id=4, name="real-tag"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    # Only the resolvable tag survives.
    assert filters.tag_ids == (4,)


# ---------------------------------------------------------------------------
# resolve_filters — date candidates pass through unchanged
# ---------------------------------------------------------------------------


def test_resolve_filters_date_candidates_pass_through() -> None:
    """resolve_filters passes date_from/date_to straight through."""
    candidates = make_filter_candidates(
        date_from="2024-01-01", date_to="2024-12-31"
    )

    filters = resolve_filters(candidates, make_facet_set(), ui_filters=None)

    assert filters.date_from == "2024-01-01"
    assert filters.date_to == "2024-12-31"


# ---------------------------------------------------------------------------
# resolve_filters — UI filters override planner candidates
# ---------------------------------------------------------------------------


def test_resolve_filters_ui_filters_override_planner_candidates() -> None:
    """When ui_filters is provided it bypasses free-text resolution entirely."""
    # The planner emitted a correspondent guess that would otherwise resolve.
    candidates = make_filter_candidates(
        correspondent="ACME Corp", date_from="2023-01-01"
    )
    facets = make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=7, name="ACME Corp"),)
    )
    # The user explicitly set a different correspondent in the UI.
    ui_filters = SearchFilters(
        date_from="2022-01-01",
        date_to="2022-12-31",
        correspondent_id=99,
        document_type_id=None,
        tag_ids=(),
    )

    filters = resolve_filters(candidates, facets, ui_filters=ui_filters)

    # The UI filter is returned as-is; the planner's guess is ignored.
    assert filters is ui_filters
    assert filters.correspondent_id == 99
    assert filters.date_from == "2022-01-01"


def test_resolve_filters_ui_filters_none_falls_back_to_resolution() -> None:
    """When ui_filters is None, planner candidates are resolved normally."""
    candidates = make_filter_candidates(correspondent="ACME Corp")
    facets = make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=7, name="ACME Corp"),)
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7
