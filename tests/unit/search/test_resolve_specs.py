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


def test_resolves_correspondent_after_case_normalisation() -> None:
    """A case-mismatched guess ("ebay") resolves via the normalised pass."""
    spec = _semantic_spec(correspondent="ebay")
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.correspondent_id == 132


def test_resolves_document_type_after_punctuation_and_case_normalisation() -> None:
    """A guess differing only by punctuation/case ("pay-slip") still resolves."""
    spec = _semantic_spec(document_type="pay-slip")
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.document_type_id == 155


def test_unresolvable_tag_is_dropped_resolvable_tags_kept() -> None:
    """An unresolvable tag is dropped; a resolvable one in the same guess is kept."""
    spec = _semantic_spec(tags=("payroll", "ghost-tag"))
    plan = RetrievalPlan(specs=(spec,))

    resolved = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert resolved[0].filters.tag_ids == (7,)


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


# ---------------------------------------------------------------------------
# H1: deterministic date safety net on the raw query
# ---------------------------------------------------------------------------


def _broad_spec(semantic: str = "find something") -> PlannedSpec:
    """A broad PlannedSpec with no date hints — mimics the degraded/fallback plan."""
    from search.models import EMPTY_FILTER_CANDIDATES

    return PlannedSpec(
        mode="semantic",
        semantic=semantic,
        keywords=(),
        filter_guess=EMPTY_FILTER_CANDIDATES,
        rationale="broad fallback",
    )


class TestDateSafetyNet:
    """resolve_specs appends a date-scoped spec when the query names a period but
    no resolved spec has a date filter (the degraded/fallback planner path)."""

    def test_safety_net_appended_for_dated_query_on_broad_plan(self) -> None:
        """A date-less broad spec + temporal query → safety-net spec appended.

        The recall-floor spec (the original broad, date-unbound spec) is
        preserved as the first spec.  The safety-net spec is second with the
        correct date range.
        """
        plan = RetrievalPlan(specs=(_broad_spec(),))

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=None,
            today=_TODAY,
            query="what was my salary in April 2025",
        )

        # Recall floor preserved — the original spec is still there.
        assert len(resolved) == 2
        broad = resolved[0]
        assert broad.filters.date_from is None
        assert broad.filters.date_to is None

        # Safety-net spec carries the April 2025 date range.
        safety = resolved[1]
        assert safety.filters.date_from == "2025-04-01"
        assert safety.filters.date_to == "2025-04-30"
        assert "safety net" in safety.rationale

    def test_safety_net_not_appended_when_spec_already_has_date(self) -> None:
        """When at least one spec already has a date filter, the safety net does not fire.

        The intentionally-unbound recall spec (if any) must stay unbound.
        """
        dated_spec = _semantic_spec(date_from="2025-04-01", date_to="2025-04-30")
        plan = RetrievalPlan(specs=(dated_spec,))

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=None,
            today=_TODAY,
            query="salary in April 2025",
        )

        # No safety-net spec added — one in, one out.
        assert len(resolved) == 1
        assert resolved[0].filters.date_from == "2025-04-01"
        assert resolved[0].filters.date_to == "2025-04-30"

    def test_safety_net_not_appended_for_non_temporal_query(self) -> None:
        """A query with no recognisable date adds no safety-net spec."""
        plan = RetrievalPlan(specs=(_broad_spec(),))

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=None,
            today=_TODAY,
            query="my salary",
        )

        assert len(resolved) == 1
        assert resolved[0].filters.date_from is None

    def test_safety_net_absent_when_no_query_supplied(self) -> None:
        """When query is omitted (defaults to ''), the safety net never fires."""
        plan = RetrievalPlan(specs=(_broad_spec(),))

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=None,
            today=_TODAY,
            # query not supplied — broadened retrieval pass, safety net off.
        )

        assert len(resolved) == 1

    def test_safety_net_intersects_ui_filters(self) -> None:
        """The safety-net spec's date is intersected with ui_filters (non-date UI constraints).

        A UI filter with a correspondent_id (but no date) does not supply a date
        itself, so the safety net still fires, and the UI correspondent is
        carried into the safety-net spec's filters.
        """
        from store.reader import SearchFilters

        plan = RetrievalPlan(specs=(_broad_spec(),))
        # UI sets a correspondent but no date — the broad spec still has no date
        # after intersection, so the safety net must fire.
        ui = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=999,
            document_type_id=None,
            tag_ids=(),
        )

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=ui,
            today=_TODAY,
            query="what was my salary in April 2025",
        )

        assert len(resolved) == 2
        safety = resolved[1]
        # Safety-net spec carries the April 2025 date range.
        assert safety.filters.date_from == "2025-04-01"
        assert safety.filters.date_to == "2025-04-30"
        # UI correspondent is preserved in the safety-net spec.
        assert safety.filters.correspondent_id == 999

    def test_recall_floor_preserved_alongside_safety_net(self) -> None:
        """The broad, date-unbound recall spec survives when safety net fires.

        Two specs in the plan; neither has a date; the query has a date.
        Both originals survive; one safety-net spec is appended.
        """
        plan = RetrievalPlan(
            specs=(
                _broad_spec("broad semantic query A"),
                _broad_spec("broad semantic query B"),
            )
        )

        resolved = resolve_specs(
            plan,
            _facets(),
            ui_filters=None,
            today=_TODAY,
            query="salary in April 2025",
        )

        # Two originals + one safety-net spec.
        assert len(resolved) == 3
        # Both originals are date-unbound.
        assert resolved[0].filters.date_from is None
        assert resolved[1].filters.date_from is None
        # Safety net is the last one.
        assert resolved[2].filters.date_from == "2025-04-01"
        assert resolved[2].filters.date_to == "2025-04-30"


# ---------------------------------------------------------------------------
# Unfiltered recall twins (max_specs)
# ---------------------------------------------------------------------------


def _empty_filters(filters: object) -> bool:
    return (
        filters.correspondent_id is None
        and filters.document_type_id is None
        and not filters.tag_ids
        and filters.date_from is None
        and filters.date_to is None
    )


def test_filtered_spec_gets_unfiltered_twin() -> None:
    """A spec with a resolved filter gains a filter-stripped twin (same query)."""
    plan = RetrievalPlan(specs=(_semantic_spec(correspondent="eBay"),))

    specs = resolve_specs(
        plan, _facets(), ui_filters=None, today=_TODAY, max_specs=8
    )

    assert len(specs) == 2
    assert specs[0].filters.correspondent_id == 132  # original keeps its filter
    assert _empty_filters(specs[1].filters)  # twin has none
    assert specs[1].semantic == specs[0].semantic  # same query
    assert specs[1].mode == specs[0].mode


def test_unfiltered_spec_gets_no_twin() -> None:
    """A spec that resolved to no filters needs no twin."""
    plan = RetrievalPlan(specs=(_semantic_spec(),))

    specs = resolve_specs(
        plan, _facets(), ui_filters=None, today=_TODAY, max_specs=8
    )

    assert len(specs) == 1


def test_twin_deduped_against_existing_unfiltered_spec() -> None:
    """A twin identical to an already-present unfiltered spec is dropped."""
    filtered = _semantic_spec(correspondent="eBay", semantic="same")
    plain = _semantic_spec(semantic="same")
    plan = RetrievalPlan(specs=(filtered, plain))

    specs = resolve_specs(
        plan, _facets(), ui_filters=None, today=_TODAY, max_specs=8
    )

    # filtered + plain only; the twin equals `plain` and is deduped away.
    assert len(specs) == 2


def test_twins_respect_max_specs_dropping_twins_not_originals() -> None:
    """At the cap, twins are dropped from the tail; originals always survive."""
    plan = RetrievalPlan(
        specs=(
            _semantic_spec(correspondent="eBay", semantic="a"),
            _semantic_spec(document_type="Payslip", semantic="b"),
        )
    )

    specs = resolve_specs(
        plan, _facets(), ui_filters=None, today=_TODAY, max_specs=3
    )

    assert len(specs) == 3  # 2 originals + 1 twin (capped)
    assert specs[0].filters.correspondent_id == 132
    assert specs[1].filters.document_type_id == 155


def test_max_specs_none_means_no_twins() -> None:
    """The default (max_specs=None) disables twinning — the broadened pass case."""
    plan = RetrievalPlan(specs=(_semantic_spec(correspondent="eBay"),))

    specs = resolve_specs(plan, _facets(), ui_filters=None, today=_TODAY)

    assert len(specs) == 1
