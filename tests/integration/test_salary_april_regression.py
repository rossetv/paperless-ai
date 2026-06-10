"""Regression eval: "What was my salary in April 2025?" surfaces the April payslip.

This test pins the motivating bug for the multi-spec retrieval overhaul:
a date-scoped semantic query must return the April 2025 payslip (doc #750)
and must NOT return the February/January decoys (#1482, #1483) that are
vector-equally-near the query but outside the April date window.

Three documents are seeded with distinct ``created`` dates and the same
embedding axis (so vector similarity cannot distinguish them — only the
``date()`` SQL filter does).

Assertions:
1. The full pipeline answer cites doc #750.
2. Date-scoped specs (``resolve_specs`` + ``Retriever.retrieve``) return #750
   and exclude both decoys.
3. The April doc (created 2025-04-25) falls within the 2025-04-01..2025-04-30
   window, exercising the ``date()`` fix end-to-end.

Split from the main pipeline tests for the 500-line ceiling
(CODE_GUIDELINES §3.1).  Seeding wiring mirrors ``test_search_pipeline.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from search.models import FilterCandidates, PlannedSpec, RetrievalPlan
from search.retriever import Retriever, resolve_specs
from store.models import ChunkInput, DocumentMeta
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    judge_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core
from tests.integration.conftest import (
    AXIS_BOILER as _AXIS_SALARY,
    make_axis_embedding_client as _make_embedding_client,
    make_pipeline_settings as _make_settings,
)

# Embedding axis shared by all three docs.  The query also lands on this axis,
# so vector similarity is identical across all three — only the date filter
# decides what each date-scoped spec returns.
_AXIS = _AXIS_SALARY

# Document ids for the three seeded payslips.
_DOC_APRIL = 750     # "eBay Payslip ... 04/2025", created 2025-04-25
_DOC_FEB = 1482      # "Rosset Payslip 02/2025",   created 2025-02-05
_DOC_JAN = 1483      # "Rosset Payslip 01/2025",   created 2025-01-05


def _seed_payslip(
    store_writer: StoreWriter,
    *,
    document_id: int,
    title: str,
    text: str,
    created: str,
) -> None:
    """Upsert one payslip document with a custom ``created`` date.

    ``seed_pipeline_document`` from conftest hard-codes ``created``; this
    helper calls ``StoreWriter.upsert_document`` directly so each doc can
    carry its real creation timestamp (the crux of the regression test).
    """
    meta = DocumentMeta(
        id=document_id,
        title=title,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
        created=created,
        modified="2025-06-10T00:00:00+00:00",
        content_hash=f"hash-{document_id}",
        page_count=1,
    )
    chunk = ChunkInput(
        chunk_index=0,
        text=text,
        page_hint=1,
        embedding=list(_AXIS),
    )
    store_writer.upsert_document(meta, [chunk])


def _seed_all(store_writer: StoreWriter) -> None:
    """Seed the three payslip documents used by every test in this module."""
    _seed_payslip(
        store_writer,
        document_id=_DOC_APRIL,
        title="eBay Payslip ... 04/2025",
        created="2025-04-25T00:00:00+00:00",
        text="Reg Salary 1923.08 Gross Pay 11923.08",
    )
    _seed_payslip(
        store_writer,
        document_id=_DOC_FEB,
        title="Rosset Payslip 02/2025",
        created="2025-02-05T00:00:00+00:00",
        text="Basic Salary 100.00",
    )
    _seed_payslip(
        store_writer,
        document_id=_DOC_JAN,
        title="Rosset Payslip 01/2025",
        created="2025-01-05T00:00:00+00:00",
        text="Basic Salary 100.00",
    )


# ---------------------------------------------------------------------------
# Focused retrieval sub-test: date filter alone excludes decoys
# ---------------------------------------------------------------------------


class TestDateFilterExcludesDecoys:
    """``resolve_specs`` + ``Retriever.retrieve`` with date-scoped specs return
    only the April doc and exclude the February and January decoys."""

    def test_date_scoped_specs_include_april_and_exclude_decoys(
        self, tmp_path: Any
    ) -> None:
        """The date filter ``2025-04-01..2025-04-30`` includes doc #750 (created
        2025-04-25) and excludes #1482 (2025-02-05) and #1483 (2025-01-05)."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            _seed_all(store_writer)
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            retriever = Retriever(
                settings,
                store_reader,
                _make_embedding_client(_AXIS),
            )

            # Build two date-scoped planned specs mirroring the planner output
            # for "What was my salary in April 2025?".
            april_filter = FilterCandidates(
                correspondent=None,
                document_type=None,
                tags=(),
                date_from="2025-04-01",
                date_to="2025-04-30",
            )
            planned_specs = (
                PlannedSpec(
                    mode="semantic",
                    semantic="my salary gross pay April 2025",
                    keywords=(),
                    filter_guess=april_filter,
                    rationale="primary date-scoped salary spec",
                ),
                PlannedSpec(
                    mode="semantic",
                    semantic="my income April 2025",
                    keywords=(),
                    filter_guess=april_filter,
                    rationale="secondary date-scoped income spec",
                ),
            )
            plan = RetrievalPlan(specs=planned_specs)
            facets = store_reader.list_facets()
            specs = resolve_specs(
                plan,
                facets,
                ui_filters=None,
                today=date(2025, 6, 10),
            )

            chunks, _signal = retriever.retrieve(specs)

            returned_doc_ids = {chunk.document_id for chunk in chunks}

            # Boundary: April doc is included by the date filter.
            assert _DOC_APRIL in returned_doc_ids, (
                f"doc #{_DOC_APRIL} (created 2025-04-25) must be within "
                "the 2025-04-01..2025-04-30 window"
            )
            # Decoys are excluded by the date filter.
            assert _DOC_FEB not in returned_doc_ids, (
                f"doc #{_DOC_FEB} (created 2025-02-05) must be excluded "
                "by the April date filter"
            )
            assert _DOC_JAN not in returned_doc_ids, (
                f"doc #{_DOC_JAN} (created 2025-01-05) must be excluded "
                "by the April date filter"
            )
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Full pipeline: the answer cites the April payslip
# ---------------------------------------------------------------------------


class TestFullPipelineAprilSalary:
    """End-to-end: "What was my salary in April 2025?" cites the April doc."""

    def test_april_salary_query_cites_april_payslip(self, tmp_path: Any) -> None:
        """The full pipeline — real planner specs, real retriever, scripted LLM
        — answers the April salary query citing doc #750 and not the decoys."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            _seed_all(store_writer)
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[
                        # Two date-scoped specs (exclude the decoys via date filter).
                        _make_spec(
                            semantic="my salary gross pay April 2025",
                            date_from="2025-04-01",
                            date_to="2025-04-30",
                            rationale="primary date-scoped salary spec",
                        ),
                        _make_spec(
                            semantic="my income April 2025",
                            date_from="2025-04-01",
                            date_to="2025-04-30",
                            rationale="secondary date-scoped income spec",
                        ),
                        # One broad spec without date — recall floor;
                        # may surface a decoy, which the judge handles.
                        _make_spec(
                            semantic="my 2025 employment income",
                            rationale="broad recall spec",
                        ),
                    ]
                ),
                judge_response=judge_response_json(
                    relevant_document_ids=[_DOC_APRIL],
                    dropped_document_ids=[_DOC_FEB, _DOC_JAN],
                ),
                synthesiser_responses=[
                    answered_response_json(
                        f"Your gross pay in April 2025 was £11,923.08 [{_DOC_APRIL}].",
                        citations=[_DOC_APRIL],
                    )
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS),
            )
            result = core.answer("What was my salary in April 2025?")

            source_ids = {source.document_id for source in result.sources}

            # The April payslip must be the (sole) cited source.
            assert _DOC_APRIL in source_ids, (
                f"doc #{_DOC_APRIL} (April 2025 payslip) must appear in result.sources"
            )
            # The decoys must not appear in the final answer's sources.
            assert _DOC_FEB not in source_ids, (
                f"doc #{_DOC_FEB} (February decoy) must not appear in result.sources"
            )
            assert _DOC_JAN not in source_ids, (
                f"doc #{_DOC_JAN} (January decoy) must not appear in result.sources"
            )
        finally:
            store_reader.close()
