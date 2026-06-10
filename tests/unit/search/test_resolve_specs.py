"""Tests for search.retriever.resolve_specs — per-spec filter resolution.

Verifies, for the multi-spec retrieval overhaul:
- A planned spec's free-text correspondent / document-type / tag guesses are
  resolved against the live taxonomy to real ids; unresolvable guesses drop to
  None / are omitted.
- A non-ISO temporal guess ("April 2025") is run through the deterministic date
  extractor; ISO bounds the planner supplied pass straight through; a malformed
  ISO guess with no other temporal text is dropped to None.
- ``ui_filters`` is a global constraint that *intersects* the resolved spec —
  it narrows (the later date_from, the earlier date_to, a UI correspondent
  overriding the spec's, a union of tag ids) but never widens.
- Spec metadata — order, mode, semantic, keywords, rationale — is preserved.
"""

from __future__ import annotations

from datetime import date

from search.models import PlannedSpec, RetrievalPlan
from search.retriever import resolve_specs
from store.reader import SearchFilters
from tests.helpers.factories import make_facet_set, make_filter_candidates
from tests.helpers.factories import make_taxonomy_entry as _entry

_TODAY = date(2026, 6, 10)


def _facets() -> object:
    """A FacetSet with one correspondent, one document type, and one tag."""
    return make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=132, name="eBay"),),
        document_types=(_entry(kind="document_type", entry_id=155, name="Payslip"),),
        tags=(_entry(kind="tag", entry_id=7, name="payroll"),),
    )


def _semantic_spec(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    semantic: str = "find something",
    rationale: str = "because",
) -> PlannedSpec:
    """Build a semantic PlannedSpec carrying the given filter guesses."""
    return PlannedSpec(
        mode="semantic",
        semantic=semantic,
        keywords=(),
        filter_guess=make_filter_candidates(
            correspondent=correspondent,
            document_type=document_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
        ),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------


def test_resolves_correspondent_and_document_type_and_month_year() -> None:
    """A full guess resolves names to ids and "April 2025" to a month range."""
    spec = _semantic_spec(
        correspondent="eBay",
        document_type="Payslip",
        date_from="April 2025",
        date_to=None,
    )
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert len(resolved) == 1
    filters = resolved[0].filters
    assert filters.correspondent_id == 132
    assert filters.document_type_id == 155
    assert filters.date_from == "2025-04-01"
    assert filters.date_to == "2025-04-30"


def test_resolves_tag_guess_to_id() -> None:
    """A resolvable tag guess becomes its taxonomy id; the rest stay empty."""
    spec = _semantic_spec(tags=("payroll",))
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.tag_ids == (7,)


def test_unresolvable_correspondent_drops_to_none() -> None:
    """A correspondent guess with no taxonomy match resolves to None, never a guess."""
    spec = _semantic_spec(correspondent="Unknown Ltd")
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.correspondent_id is None


# ---------------------------------------------------------------------------
# Dates: ISO pass-through, deterministic extraction, malformed dropping
# ---------------------------------------------------------------------------


def test_iso_bounds_pass_through_unchanged() -> None:
    """Planner-supplied ISO bounds are validated and passed straight through."""
    spec = _semantic_spec(date_from="2025-04-01", date_to="2025-04-30")
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.date_from == "2025-04-01"
    assert resolved[0].filters.date_to == "2025-04-30"


def test_malformed_iso_with_no_other_temporal_text_drops_to_none() -> None:
    """A malformed ISO date_from with no other temporal expression drops to None."""
    spec = _semantic_spec(date_from="notadate", date_to=None)
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.date_from is None
    assert resolved[0].filters.date_to is None


# ---------------------------------------------------------------------------
# UI intersection — narrows, never widens
# ---------------------------------------------------------------------------


def test_ui_date_to_intersects_to_the_earlier_bound() -> None:
    """A UI date_to earlier than the spec's narrows the resolved upper bound."""
    spec = _semantic_spec(date_from="2025-04-01", date_to="2025-04-30")
    plan = RetrievalPlan(specs=(spec,))
    ui = SearchFilters(
        date_from=None,
        date_to="2025-04-15",
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )

    resolved = resolve_specs(plan, _facets(), ui_filters=ui, today=_TODAY)

    # date_to becomes the earlier of (2025-04-30, 2025-04-15); date_from is the
    # spec's (the UI left it unbounded).
    assert resolved[0].filters.date_from == "2025-04-01"
    assert resolved[0].filters.date_to == "2025-04-15"


def test_ui_correspondent_overrides_the_spec() -> None:
    """A UI correspondent_id AND-narrows, overriding whatever the spec resolved."""
    spec = _semantic_spec(correspondent="eBay")  # resolves to 132
    plan = RetrievalPlan(specs=(spec,))
    ui = SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=999,
        document_type_id=None,
        tag_ids=(),
    )

    resolved = resolve_specs(plan, _facets(), ui_filters=ui, today=_TODAY)

    assert resolved[0].filters.correspondent_id == 999


def test_ui_tag_ids_union_with_spec_tag_ids() -> None:
    """Tag ids are the de-duplicated, order-stable union of spec and UI."""
    spec = _semantic_spec(tags=("payroll",))  # resolves to 7
    plan = RetrievalPlan(specs=(spec,))
    ui = SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(7, 42),
    )

    resolved = resolve_specs(plan, _facets(), ui_filters=ui, today=_TODAY)

    assert resolved[0].filters.tag_ids == (7, 42)


def test_ui_date_from_takes_the_later_bound() -> None:
    """When both set date_from, the resolved lower bound is the later (max)."""
    spec = _semantic_spec(date_from="2025-04-01", date_to="2025-04-30")
    plan = RetrievalPlan(specs=(spec,))
    ui = SearchFilters(
        date_from="2025-04-10",
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )

    resolved = resolve_specs(plan, _facets(), ui_filters=ui, today=_TODAY)

    assert resolved[0].filters.date_from == "2025-04-10"
    assert resolved[0].filters.date_to == "2025-04-30"


# ---------------------------------------------------------------------------
# Spec metadata preservation across multiple specs
# ---------------------------------------------------------------------------


def test_order_and_metadata_preserved_across_specs() -> None:
    """mode / semantic / keywords / rationale and order survive resolution."""
    spec_a = PlannedSpec(
        mode="semantic",
        semantic="first query",
        keywords=(),
        filter_guess=make_filter_candidates(correspondent="eBay"),
        rationale="first rationale",
    )
    spec_b = PlannedSpec(
        mode="keyword",
        semantic=None,
        keywords=("invoice", "2025"),
        filter_guess=make_filter_candidates(document_type="Payslip"),
        rationale="second rationale",
    )
    plan = RetrievalPlan(specs=(spec_a, spec_b))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert len(resolved) == 2
    assert resolved[0].mode == "semantic"
    assert resolved[0].semantic == "first query"
    assert resolved[0].keywords == ()
    assert resolved[0].rationale == "first rationale"
    assert resolved[0].filters.correspondent_id == 132

    assert resolved[1].mode == "keyword"
    assert resolved[1].semantic is None
    assert resolved[1].keywords == ("invoice", "2025")
    assert resolved[1].rationale == "second rationale"
    assert resolved[1].filters.document_type_id == 155
