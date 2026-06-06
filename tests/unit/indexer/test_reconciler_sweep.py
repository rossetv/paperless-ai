"""Tests for indexer.reconciler deletion sweep (SPEC §5.4 — safety rules).

deletion_sweep:
- A complete enumeration prunes ONLY the truly-absent ids.
- An enumeration that raises mid-pagination prunes NOTHING (the data-loss
  prevention case).
- A candidate that document_exists still confirms present is NOT pruned.

The incremental sync lives in test_reconciler_incremental.py; the bounded
failed-document retry in test_reconciler_failed_documents.py — the reconciler's
tests mirror the indexer/reconciler/ package split (CODE_GUIDELINES §11.2).
The Paperless and StoreWriter mock builders come from
tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from indexer.reconciler import Reconciler, SweepReport
from tests.helpers.mocks import make_mock_embedding_client
from tests.helpers.factories import make_settings_obj
from tests.unit.indexer.conftest import (
    make_reconciler_paperless,
    make_reconciler_store_writer,
)


def _reconciler(paperless: MagicMock, store_writer: MagicMock) -> Reconciler:
    """Build a Reconciler over the given mocks — the sweep ignores the worker."""
    return Reconciler(
        make_settings_obj(), paperless, store_writer, make_mock_embedding_client()
    )


# ---------------------------------------------------------------------------
# A complete enumeration prunes ONLY the truly-absent ids
# ---------------------------------------------------------------------------


class TestDeletionSweepCompleteEnumeration:
    """A complete enumeration prunes ONLY the truly-absent ids."""

    def test_prunes_only_ids_absent_from_paperless(self) -> None:
        # Paperless has 1 and 2; the store also has a stale 3 and 4.
        paperless = make_reconciler_paperless(all_ids=[1, 2])
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3, 4})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        store_writer.delete_documents.assert_called_once()
        pruned = set(store_writer.delete_documents.call_args[0][0])
        assert pruned == {3, 4}
        assert report.pruned == 2

    def test_nothing_to_prune_when_store_matches_paperless(self) -> None:
        paperless = make_reconciler_paperless(all_ids=[1, 2, 3])
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        assert report.pruned == 0
        if store_writer.delete_documents.called:
            assert set(store_writer.delete_documents.call_args[0][0]) == set()

    def test_completed_sweep_records_last_full_sweep_at(self) -> None:
        paperless = make_reconciler_paperless(all_ids=[1])
        store_writer = make_reconciler_store_writer(store_ids={1})

        _reconciler(paperless, store_writer).deletion_sweep()

        assert "last_full_sweep_at" in store_writer._meta

    def test_empty_complete_enumeration_prunes_every_confirmed_absent_document(
        self,
    ) -> None:
        """The dangerous boundary: a SUCCESSFUL enumeration yielding zero ids.

        Paperless genuinely has no documents.  ``iter_all_documents()``
        completes normally yielding ``[]`` — it does NOT raise — so the
        enumeration is authoritative, and every store document, once
        404-confirmed absent, is pruned.  This is distinct from an enumeration
        that *fails* and returns nothing: that one aborts.
        """
        paperless = make_reconciler_paperless(all_ids=[])  # successful, empty
        # document_exists returns False by default → all confirmed absent.
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        assert report.aborted is False
        assert report.candidates == 3
        assert report.pruned == 3
        store_writer.delete_documents.assert_called_once()
        assert set(store_writer.delete_documents.call_args[0][0]) == {1, 2, 3}
        assert "last_full_sweep_at" in store_writer._meta

    def test_empty_enumeration_keeps_documents_the_404_confirm_says_exist(
        self,
    ) -> None:
        """Even on an empty enumeration, a candidate the 404-confirm reports
        PRESENT is kept — the per-id confirmation is the real deletion guard."""
        paperless = make_reconciler_paperless(all_ids=[])  # successful, empty
        # The enumeration listed nothing, but id 2 actually still exists.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        assert report.aborted is False
        # id 2 was confirmed present → survives; 1 and 3 → pruned.
        assert report.pruned == 2
        assert set(store_writer.delete_documents.call_args[0][0]) == {1, 3}


# ---------------------------------------------------------------------------
# A mid-pagination failure must prune NOTHING
# ---------------------------------------------------------------------------


class TestDeletionSweepPartialEnumerationPrunesNothing:
    """THE critical case: a mid-pagination failure must prune NOTHING."""

    def test_page_failure_mid_enumeration_prunes_nothing(self) -> None:
        """If iter_all_documents raises mid-pagination, the store is untouched.

        A partial enumeration would make every not-yet-seen document look
        deleted.  The sweep must abort and prune NOTHING (SPEC §5.4 rule 2).
        """
        paperless = MagicMock()

        def _iter_all_documents(
            *, modified_after: str | None = None, fields: tuple[str, ...] | None = None
        ):
            # Yield a couple of ids, then fail mid-pagination.
            yield {"id": 1}
            yield {"id": 2}
            raise ConnectionError("Paperless unreachable mid-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents

        # The store holds ids NOT in the partial enumeration; a naive diff
        # would prune 3, 4, 5 — that is the data-loss footgun.
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3, 4, 5})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        # The store must be completely untouched.
        store_writer.delete_documents.assert_not_called()
        assert report.pruned == 0
        assert report.aborted is True
        # The sweep did not complete, so last_full_sweep_at must not advance.
        assert "last_full_sweep_at" not in store_writer._meta

    def test_first_page_failure_prunes_nothing(self) -> None:
        """An immediate enumeration failure also prunes nothing."""
        paperless = MagicMock()

        def _iter_all_documents(
            *, modified_after: str | None = None, fields: tuple[str, ...] | None = None
        ):
            raise ConnectionError("Paperless down before the first page")
            yield  # pragma: no cover — unreachable, makes this a generator

        paperless.iter_all_documents.side_effect = _iter_all_documents
        store_writer = make_reconciler_store_writer(store_ids={10, 11, 12})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        store_writer.delete_documents.assert_not_called()
        assert report.aborted is True
        assert report.pruned == 0


# ---------------------------------------------------------------------------
# Each candidate is 404-confirmed before it is pruned (SPEC §5.4 rule 3)
# ---------------------------------------------------------------------------


class TestDeletionSweepConfirmsBeforePruning:
    """Each candidate is 404-confirmed before it is pruned (SPEC §5.4 rule 3)."""

    def test_candidate_still_present_is_not_pruned(self) -> None:
        """A candidate that document_exists confirms PRESENT is kept.

        document_exists is the second confirmation against a race: the document
        appeared absent from the page enumeration but actually still exists.
        """
        # Enumeration says Paperless has only id 1; the store has 1 and 2.
        paperless = make_reconciler_paperless(all_ids=[1])
        # But the per-id confirmation says id 2 DOES still exist.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = make_reconciler_store_writer(store_ids={1, 2})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        # id 2 was confirmed present → it must not be pruned.
        assert report.pruned == 0
        if store_writer.delete_documents.called:
            assert 2 not in set(store_writer.delete_documents.call_args[0][0])

    def test_only_confirmed_absent_candidates_are_pruned(self) -> None:
        """When several candidates exist, only the 404-confirmed ones are pruned."""
        paperless = make_reconciler_paperless(all_ids=[1])
        # id 2 still exists (race); id 3 and id 4 are genuinely gone.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3, 4})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        pruned = set(store_writer.delete_documents.call_args[0][0])
        assert pruned == {3, 4}
        assert report.pruned == 2

    def test_document_exists_is_called_for_each_candidate(self) -> None:
        paperless = make_reconciler_paperless(all_ids=[1])
        store_writer = make_reconciler_store_writer(store_ids={1, 5, 6})

        _reconciler(paperless, store_writer).deletion_sweep()

        confirmed = {call.args[0] for call in paperless.document_exists.call_args_list}
        assert confirmed == {5, 6}


# ---------------------------------------------------------------------------
# IDX-03 perf: the enumeration projects to the id field only
# ---------------------------------------------------------------------------


class TestSweepEnumerationUsesLightProjection:
    """The sweep enumerates ids with a fields=('id',) projection (IDX-03 perf)."""

    def test_enumeration_requests_only_the_id_field(self) -> None:
        paperless = make_reconciler_paperless(all_ids=[1, 2, 3])
        # Store holds the same ids → no candidates → no pruning, but the
        # enumeration still runs and must use the light projection.
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        _reconciler(paperless, store_writer).deletion_sweep()

        # The unfiltered enumeration call (no modified_after) carried fields=("id",).
        sweep_calls = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if "modified_after" not in call.kwargs
        ]
        assert len(sweep_calls) == 1
        assert sweep_calls[0].kwargs.get("fields") == ("id",)


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


class TestSweepReportShape:
    """SweepReport is a frozen dataclass (SPEC contract)."""

    def test_sweep_report_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        report = SweepReport(pruned=0, aborted=False, candidates=0)
        with pytest.raises(FrozenInstanceError):
            report.pruned = 99  # type: ignore[misc]
