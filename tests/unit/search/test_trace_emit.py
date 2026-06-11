"""Tests for Tasks 3 and 4 of the search trace redesign.

Calls the private emit helpers (_emit_resolve_phase, _trace_chunks,
_gate_documents) directly with hand-built fixtures and a real _Telemetry
instance so the assertions are tightly scoped to the shape of the emitted
detail dicts, without needing a full end-to-end search.
"""

from __future__ import annotations

import pytest

from search.core import SearchCore, _gate_documents, _trace_chunks
from search.models import (
    PlannedSpec,
    RetrievalPlan,
    RetrievalSpec,
)
from search.trace import PhaseRecord, _Telemetry
from tests.helpers.factories import (
    make_facet_set,
    make_filter_candidates,
    make_indexed_document,
    make_planned_spec,
    make_retrieved_chunk,
    make_search_filters,
    make_taxonomy_entry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tele() -> tuple[_Telemetry, list[PhaseRecord]]:
    """Return a (telemetry, records_list) pair; records accumulate on done()."""
    records: list[PhaseRecord] = []
    tele = _Telemetry(on_event=records.append, provider="openai")
    return tele, records


def _record(records: list[PhaseRecord], phase: str) -> PhaseRecord:
    return next(r for r in records if isinstance(r, PhaseRecord) and r.phase == phase)


def _planned_spec(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
) -> PlannedSpec:
    return make_planned_spec(
        filter_guess=make_filter_candidates(
            correspondent=correspondent,
            document_type=document_type,
            tags=tags,
        )
    )


def _spec(
    *,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    tag_ids: tuple[int, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> RetrievalSpec:
    return RetrievalSpec(
        mode="semantic",
        semantic="test",
        keywords=(),
        filters=make_search_filters(
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
        ),
        rationale="test",
    )


# ---------------------------------------------------------------------------
# Task 3: resolve phase emit
# ---------------------------------------------------------------------------


class TestResolvePhaseEmitResolved:
    def test_resolved_emits_id_name_method_for_loose_match(self) -> None:
        """A "Deed" guess that loosely matches "Property Deed" → method "loose"."""
        facets = make_facet_set(
            document_types=(
                make_taxonomy_entry(
                    kind="document_type", entry_id=42, name="Property Deed"
                ),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(document_type="Deed"),))
        specs = (_spec(document_type_id=42),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        detail = _record(records, "resolve").detail
        resolved = detail["resolved"]
        assert len(resolved) == 1
        assert resolved[0]["document_type"] == {
            "id": 42,
            "name": "Property Deed",
            "method": "loose",
        }

    def test_resolved_emits_exact_method_for_exact_match(self) -> None:
        facets = make_facet_set(
            correspondents=(
                make_taxonomy_entry(kind="correspondent", entry_id=10, name="HMRC"),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(correspondent="HMRC"),))
        specs = (_spec(correspondent_id=10),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        detail = _record(records, "resolve").detail
        assert detail["resolved"][0]["correspondent"] == {
            "id": 10,
            "name": "HMRC",
            "method": "exact",
        }

    def test_resolved_emits_none_for_unguessed_field(self) -> None:
        """A spec with no correspondent guess → correspondent field is None."""
        facets = make_facet_set(
            document_types=(
                make_taxonomy_entry(kind="document_type", entry_id=5, name="Payslip"),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(document_type="Payslip"),))
        specs = (_spec(document_type_id=5),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        assert (
            _record(records, "resolve").detail["resolved"][0]["correspondent"] is None
        )

    def test_resolved_includes_date_bounds(self) -> None:
        facets = make_facet_set()
        plan = RetrievalPlan(specs=(_planned_spec(),))
        spec = _spec(date_from="2025-01-01", date_to="2025-12-31")

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, (spec,), facets, tele)

        r = _record(records, "resolve").detail["resolved"][0]
        assert r["date_from"] == "2025-01-01"
        assert r["date_to"] == "2025-12-31"

    def test_safety_net_spec_is_excluded_from_resolved(self) -> None:
        """The safety-net spec (beyond plan.specs length) is not emitted in resolved."""
        facets = make_facet_set()
        plan = RetrievalPlan(specs=(_planned_spec(),))
        # Two specs but only one planned spec — the second is the safety-net extra.
        specs = (_spec(), _spec(document_type_id=99))

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        # Only the planned spec is emitted.
        assert len(_record(records, "resolve").detail["resolved"]) == 1

    def test_resolved_tag_emitted_with_method(self) -> None:
        facets = make_facet_set(
            tags=(make_taxonomy_entry(kind="tag", entry_id=7, name="payroll"),)
        )
        plan = RetrievalPlan(specs=(_planned_spec(tags=("payroll",)),))
        specs = (_spec(tag_ids=(7,)),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        tags = _record(records, "resolve").detail["resolved"][0]["tags"]
        assert len(tags) == 1
        assert tags[0] == {"id": 7, "name": "payroll", "method": "exact"}


class TestResolvePhaseEmitDropped:
    def test_dropped_no_match(self) -> None:
        """A guess that matches nothing → dropped with reason "none"."""
        facets = make_facet_set(
            document_types=(
                make_taxonomy_entry(kind="document_type", entry_id=1, name="Payslip"),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(document_type="Completely Unknown"),))
        specs = (_spec(),)  # no document_type_id applied

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        dropped = _record(records, "resolve").detail["dropped"]
        assert len(dropped) == 1
        assert dropped[0] == {
            "name": "Completely Unknown",
            "reason": "none",
            "candidates": [],
        }

    def test_dropped_ambiguous(self) -> None:
        """A guess that loosely matches multiple entries → dropped with reason "ambiguous"."""
        facets = make_facet_set(
            document_types=(
                make_taxonomy_entry(
                    kind="document_type", entry_id=1, name="Property Deed"
                ),
                make_taxonomy_entry(
                    kind="document_type", entry_id=2, name="Trust Deed"
                ),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(document_type="Deed"),))
        specs = (_spec(),)  # ambiguous → no id applied

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        dropped = _record(records, "resolve").detail["dropped"]
        assert len(dropped) == 1
        entry = dropped[0]
        assert entry["name"] == "Deed"
        assert entry["reason"] == "ambiguous"
        assert set(entry["candidates"]) == {"Property Deed", "Trust Deed"}

    def test_dropped_tag_no_match(self) -> None:
        """A tag guess that matches nothing → one dropped entry per unmatched tag."""
        facets = make_facet_set(
            tags=(make_taxonomy_entry(kind="tag", entry_id=3, name="mortgage"),)
        )
        plan = RetrievalPlan(specs=(_planned_spec(tags=("nonexistent-tag",)),))
        specs = (_spec(tag_ids=()),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        dropped = _record(records, "resolve").detail["dropped"]
        assert len(dropped) == 1
        assert dropped[0]["name"] == "nonexistent-tag"
        assert dropped[0]["reason"] == "none"

    def test_no_dropped_when_all_resolve(self) -> None:
        facets = make_facet_set(
            correspondents=(
                make_taxonomy_entry(kind="correspondent", entry_id=5, name="Vodafone"),
            )
        )
        plan = RetrievalPlan(specs=(_planned_spec(correspondent="Vodafone"),))
        specs = (_spec(correspondent_id=5),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        assert _record(records, "resolve").detail["dropped"] == []

    def test_no_dropped_when_no_guesses(self) -> None:
        """A spec with no filter guesses → no dropped entries."""
        facets = make_facet_set()
        plan = RetrievalPlan(specs=(_planned_spec(),))
        specs = (_spec(),)

        tele, records = _tele()
        SearchCore._emit_resolve_phase(plan, specs, facets, tele)

        assert _record(records, "resolve").detail["dropped"] == []


# ---------------------------------------------------------------------------
# Task 4: retrieve phase — _trace_chunks helper
# ---------------------------------------------------------------------------


class TestTraceChunks:
    def test_sorted_by_similarity_descending(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, vector_similarity=0.5),
            make_retrieved_chunk(chunk_id=2, document_id=2, vector_similarity=0.9),
            make_retrieved_chunk(chunk_id=3, document_id=3, vector_similarity=0.7),
        ]
        docs = {1: make_indexed_document(document_id=1, title="Alpha")}
        result = _trace_chunks(chunks, docs)

        sims = [r["vector_similarity"] for r in result]
        assert sims == [0.9, 0.7, 0.5]

    def test_none_similarity_is_last(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, vector_similarity=None),
            make_retrieved_chunk(chunk_id=2, document_id=2, vector_similarity=0.6),
        ]
        result = _trace_chunks(chunks, {})
        assert result[0]["vector_similarity"] == 0.6
        assert result[1]["vector_similarity"] is None

    def test_title_from_lookup(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=10, vector_similarity=0.8)
        ]
        docs = {10: make_indexed_document(document_id=10, title="Land Registry Deed")}
        result = _trace_chunks(chunks, docs)
        assert result[0]["title"] == "Land Registry Deed"

    def test_title_fallback_when_doc_missing(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=99, vector_similarity=0.5)
        ]
        result = _trace_chunks(chunks, {})  # empty lookup
        assert result[0]["title"] == "Document 99"

    def test_snippet_is_whitespace_collapsed(self) -> None:
        chunks = [
            make_retrieved_chunk(
                chunk_id=1,
                document_id=1,
                text="  This   has  extra   whitespace.  ",
                vector_similarity=0.5,
            )
        ]
        result = _trace_chunks(chunks, {})
        assert result[0]["snippet"] == "This has extra whitespace."

    def test_snippet_truncated_at_160_chars(self) -> None:
        long_text = "word " * 50  # well over 160 chars
        chunks = [
            make_retrieved_chunk(
                chunk_id=1, document_id=1, text=long_text, vector_similarity=0.5
            )
        ]
        result = _trace_chunks(chunks, {})
        snippet = result[0]["snippet"]
        assert len(snippet) <= 162  # 160 chars + possible ellipsis (1 char)
        assert snippet.endswith("…")

    def test_all_fields_present(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=7, document_id=3, vector_similarity=0.4)
        ]
        result = _trace_chunks(chunks, {})
        assert set(result[0].keys()) == {
            "chunk_id",
            "document_id",
            "title",
            "snippet",
            "text",
            "vector_similarity",
        }
        assert result[0]["chunk_id"] == 7
        assert result[0]["document_id"] == 3

    def test_text_is_full_untruncated_chunk(self) -> None:
        # The popover shows the whole chunk, so `text` is the full (whitespace-
        # collapsed) passage — NOT capped at 160 chars like `snippet`.
        long_text = "word " * 60  # 300 chars, well over the snippet cap
        chunks = [
            make_retrieved_chunk(
                chunk_id=1, document_id=1, text=long_text, vector_similarity=0.5
            )
        ]
        result = _trace_chunks(chunks, {})
        assert result[0]["text"] == ("word " * 59) + "word"  # collapsed, untruncated
        assert len(str(result[0]["text"])) > 160
        assert str(result[0]["snippet"]).endswith("…")  # snippet still truncates

    def test_all_chunks_emitted(self) -> None:
        chunks = [
            make_retrieved_chunk(
                chunk_id=i, document_id=i, vector_similarity=float(i) / 10
            )
            for i in range(1, 8)
        ]
        result = _trace_chunks(chunks, {})
        assert len(result) == 7


# ---------------------------------------------------------------------------
# Task 4: gate phase — _gate_documents helper
# ---------------------------------------------------------------------------


class TestGateDocuments:
    def test_best_similarity_per_document(self) -> None:
        """Best similarity over multiple chunks of the same document is taken."""
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, vector_similarity=0.4),
            make_retrieved_chunk(chunk_id=2, document_id=1, vector_similarity=0.8),
            make_retrieved_chunk(chunk_id=3, document_id=2, vector_similarity=0.6),
        ]
        result = _gate_documents(chunks, {})
        by_doc = {r["document_id"]: r["best_similarity"] for r in result}
        assert by_doc[1] == pytest.approx(0.8)
        assert by_doc[2] == pytest.approx(0.6)

    def test_sorted_by_best_similarity_descending(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, vector_similarity=0.3),
            make_retrieved_chunk(chunk_id=2, document_id=2, vector_similarity=0.9),
            make_retrieved_chunk(chunk_id=3, document_id=3, vector_similarity=0.6),
        ]
        result = _gate_documents(chunks, {})
        sims = [r["best_similarity"] for r in result]
        assert sims == sorted(sims, reverse=True)

    def test_title_from_lookup(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=5, vector_similarity=0.7)
        ]
        docs = {5: make_indexed_document(document_id=5, title="Tax Return 2024")}
        result = _gate_documents(chunks, docs)
        assert result[0]["title"] == "Tax Return 2024"

    def test_title_fallback_when_doc_absent(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=77, vector_similarity=0.5)
        ]
        result = _gate_documents(chunks, {})
        assert result[0]["title"] == "Document 77"

    def test_chunks_with_none_similarity_excluded(self) -> None:
        """Documents whose every chunk has None similarity don't appear."""
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, vector_similarity=None),
            make_retrieved_chunk(chunk_id=2, document_id=2, vector_similarity=0.5),
        ]
        result = _gate_documents(chunks, {})
        doc_ids = [r["document_id"] for r in result]
        assert 1 not in doc_ids
        assert 2 in doc_ids

    def test_all_fields_present(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=4, vector_similarity=0.6)
        ]
        result = _gate_documents(chunks, {})
        assert set(result[0].keys()) == {"document_id", "title", "best_similarity"}

    def test_empty_chunks_returns_empty(self) -> None:
        assert _gate_documents([], {}) == []
