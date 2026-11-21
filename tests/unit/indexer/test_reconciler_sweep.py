"""Tests for the reconciler's deletion sweep and its safety rules."""

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
    """Build a Reconciler over the given mocks; the sweep ignores the worker."""
    return Reconciler(
        make_settings_obj(), paperless, store_writer, make_mock_embedding_client()
    )


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
        """A successful enumeration of zero ids is authoritative, unlike a failed
        one, so every 404-confirmed store document is pruned."""
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
        """The per-id 404 confirmation is the real deletion guard."""
        paperless = make_reconciler_paperless(all_ids=[])  # successful, empty
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        assert report.aborted is False
        assert report.pruned == 2
        assert set(store_writer.delete_documents.call_args[0][0]) == {1, 3}


class TestDeletionSweepPartialEnumerationPrunesNothing:
    """A partial enumeration would make every unseen document look deleted."""

    def test_page_failure_mid_enumeration_prunes_nothing(self) -> None:
        paperless = MagicMock()

        def _iter_all_documents(
            *, modified_after: str | None = None, fields: tuple[str, ...] | None = None
        ):
            yield {"id": 1}
            yield {"id": 2}
            raise ConnectionError("Paperless unreachable mid-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents

        # A naive diff against the partial enumeration would prune 3, 4, 5.
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3, 4, 5})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        store_writer.delete_documents.assert_not_called()
        assert report.pruned == 0
        assert report.aborted is True
        assert "last_full_sweep_at" not in store_writer._meta

    def test_first_page_failure_prunes_nothing(self) -> None:
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


class TestDeletionSweepConfirmsBeforePruning:
    """Each candidate is 404-confirmed before it is pruned."""

    def test_candidate_still_present_is_not_pruned(self) -> None:
        """The per-id check guards against a document missed by the enumeration."""
        paperless = make_reconciler_paperless(all_ids=[1])
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = make_reconciler_store_writer(store_ids={1, 2})

        report = _reconciler(paperless, store_writer).deletion_sweep()

        assert report.pruned == 0
        if store_writer.delete_documents.called:
            assert 2 not in set(store_writer.delete_documents.call_args[0][0])

    def test_only_confirmed_absent_candidates_are_pruned(self) -> None:
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


class TestSweepEnumerationUsesLightProjection:
    """The sweep enumerates ids with a ``fields=("id",)`` projection."""

    def test_enumeration_requests_only_the_id_field(self) -> None:
        paperless = make_reconciler_paperless(all_ids=[1, 2, 3])
        store_writer = make_reconciler_store_writer(store_ids={1, 2, 3})

        _reconciler(paperless, store_writer).deletion_sweep()

        sweep_calls = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if "modified_after" not in call.kwargs
        ]
        assert len(sweep_calls) == 1
        assert sweep_calls[0].kwargs.get("fields") == ("id",)


class TestSweepReportShape:
    def test_sweep_report_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        report = SweepReport(pruned=0, aborted=False, candidates=0)
        with pytest.raises(FrozenInstanceError):
            report.pruned = 99  # type: ignore[misc]
