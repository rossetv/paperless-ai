"""Integration tests for the evidence-gated, reconciling synthesiser (Phase 3B).

These exercise the real :class:`~search.core.SearchCore` over the real planner,
retriever, judge, and synthesiser stages and a real
:class:`~store.reader.StoreReader` reading a ``tmp_path`` SQLite store. Only the
LLM transport and the embedding client are mocked.

The synthesiser model is scripted, so these tests verify *plumbing*, not model
judgement:

1. **Evidence-gating plumbing.** When only off-period documents are seeded
   (February / January payslips for an April question), a scripted honest "no
   April data" answer flows through as the result's answer — the pipeline does
   not silently substitute a decoy — AND the user message the synthesiser
   received carries the documents' title + date headers, so a real model would
   have the metadata it needs to refuse the substitution.
2. **Reconciliation plumbing.** When two genuinely-relevant documents are
   present and the answer cites both, both citations flow through to the result's
   sources.
"""

from __future__ import annotations

from typing import Any

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
    AXIS_BOILER as _AXIS,
)
from tests.integration.conftest import (
    make_axis_embedding_client as _make_embedding_client,
)
from tests.integration.conftest import (
    make_pipeline_settings as _make_settings,
)
from tests.integration.conftest import (
    seed_pipeline_document as _seed_document,
)

_DOC_FEB = 1482
_DOC_JAN = 1483


class _CapturingSynthClient(ScriptedLLMClient):
    """A scripted client that records the synthesiser's user message verbatim."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.synth_user_messages: list[str] = []

    def route(self, *, model: str, messages: list[dict[str, str]], **kw: Any) -> Any:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "answer-synthesis engine" in system:
            self.synth_user_messages.append(
                next((m["content"] for m in messages if m["role"] == "user"), "")
            )
        return super().route(model=model, messages=messages, **kw)


class TestEvidenceGatingPlumbing:
    """Off-period docs + a scripted honest refusal → no fabrication, metadata sent."""

    def test_no_april_answer_flows_through_with_metadata_headers(
        self, tmp_path: Any
    ) -> None:
        settings = _make_settings(tmp_path, SEARCH_GATE_JUDGE=True)
        store_writer = StoreWriter(settings)
        try:
            _seed_document(
                store_writer,
                document_id=_DOC_FEB,
                title="Rosset Payslip 02/2025",
                text="Basic Salary 100.00",
                embedding=_AXIS,
                created="2025-02-05T00:00:00+00:00",
            )
            _seed_document(
                store_writer,
                document_id=_DOC_JAN,
                title="Rosset Payslip 01/2025",
                text="Basic Salary 100.00",
                embedding=_AXIS,
                created="2025-01-05T00:00:00+00:00",
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            honest = (
                "I don't have a payslip for April 2025; the documents I have are "
                f"for February [{_DOC_FEB}] and January [{_DOC_JAN}]."
            )
            llm_client = _CapturingSynthClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="my salary April 2025")]
                ),
                judge_response=judge_response_json([_DOC_FEB, _DOC_JAN]),
                synthesiser_responses=[
                    answered_response_json(honest, citations=[_DOC_FEB, _DOC_JAN])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS),
            )
            result = core.answer("What was my salary in April 2025?")

            # The honest refusal flows through unchanged — no decoy was passed
            # off as the answer.
            assert result.answer == honest

            # The synthesiser was given the documents' title + date headers, so a
            # real model could refuse the substitution on the evidence.
            assert llm_client.synth_user_messages, "synthesiser was never called"
            synth_msg = llm_client.synth_user_messages[0]
            assert f"[{_DOC_FEB}] Rosset Payslip 02/2025 (2025-02-05)" in synth_msg
            assert f"[{_DOC_JAN}] Rosset Payslip 01/2025 (2025-01-05)" in synth_msg
        finally:
            store_reader.close()


class TestReconciliationPlumbing:
    """Two relevant documents, both cited → both citations reach the sources."""

    def test_both_cited_documents_flow_through(self, tmp_path: Any) -> None:
        settings = _make_settings(tmp_path, SEARCH_GATE_JUDGE=True)
        store_writer = StoreWriter(settings)
        try:
            _seed_document(
                store_writer,
                document_id=10,
                title="Worcester Bosch Boiler Warranty",
                text="The boiler warranty is valid until March 2028.",
                embedding=_AXIS,
            )
            _seed_document(
                store_writer,
                document_id=11,
                title="Boiler Service Record 2024",
                text="The boiler was serviced on 2024-03-15 by British Gas.",
                embedding=_AXIS,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            answer = (
                "The warranty runs to March 2028 [10]; the boiler was last "
                "serviced on 2024-03-15 [11]."
            )
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="boiler warranty and service")]
                ),
                judge_response=judge_response_json([10, 11]),
                synthesiser_responses=[
                    answered_response_json(answer, citations=[10, 11])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS),
            )
            result = core.answer("Boiler warranty and last service?")

            source_ids = {s.document_id for s in result.sources}
            assert source_ids == {10, 11}
            assert result.answer == answer
        finally:
            store_reader.close()
