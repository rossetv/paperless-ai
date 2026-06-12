"""Tests for common.stale_lock."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.stale_lock import recover_stale_locks

MODULE = "common.stale_lock"


class TestRecoverStaleLocks:
    """Tests for recover_stale_locks().

    Every test passes ``recovery_enabled=True`` explicitly so the sweep runs
    without consulting ``current_settings()`` — the flag-resolution path has its
    own dedicated tests below.
    """

    def test_returns_zero_when_processing_tag_id_is_none(self):
        client = MagicMock()

        result = recover_stale_locks(
            client, processing_tag_id=None, pre_tag_id=1, recovery_enabled=True
        )

        assert result == 0
        client.get_documents_by_tag.assert_not_called()

    def test_processing_tag_id_zero_is_valid(self):
        """Tag ID 0 is a valid Paperless tag ID and should trigger recovery."""
        client = MagicMock()
        client.get_documents_by_tag.return_value = []

        result = recover_stale_locks(
            client, processing_tag_id=0, pre_tag_id=1, recovery_enabled=True
        )

        assert result == 0
        client.get_documents_by_tag.assert_called_once_with(0)

    def test_recovers_single_stale_document(self):
        client = MagicMock()
        processing_tag = 50
        pre_tag = 10
        doc = {"id": 1, "tags": [50, 99]}
        client.get_documents_by_tag.return_value = [doc]

        result = recover_stale_locks(
            client,
            processing_tag_id=processing_tag,
            pre_tag_id=pre_tag,
            recovery_enabled=True,
        )

        assert result == 1
        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert processing_tag not in updated_tags
        assert pre_tag in updated_tags
        assert 99 in updated_tags

    def test_recovers_multiple_documents(self):
        client = MagicMock()
        processing_tag = 50
        pre_tag = 10
        docs = [
            {"id": 1, "tags": [50, 100]},
            {"id": 2, "tags": [50, 200]},
            {"id": 3, "tags": [50, 300]},
        ]
        client.get_documents_by_tag.return_value = docs

        result = recover_stale_locks(
            client,
            processing_tag_id=processing_tag,
            pre_tag_id=pre_tag,
            recovery_enabled=True,
        )

        assert result == 3
        assert client.update_document_metadata.call_count == 3

    def test_handles_query_failure_gracefully(self):
        client = MagicMock()
        client.get_documents_by_tag.side_effect = ConnectionError("API down")

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=True,
        )

        assert result == 0

    def test_handles_single_doc_update_failure_continues_with_rest(self):
        client = MagicMock()
        docs = [
            {"id": 1, "tags": [50]},
            {"id": 2, "tags": [50]},
            {"id": 3, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs
        # Second document fails
        client.update_document_metadata.side_effect = [
            None,  # doc 1 OK
            ConnectionError("update failed"),  # doc 2 fails
            None,  # doc 3 OK
        ]

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=True,
        )

        assert result == 2  # only doc 1 and doc 3 counted
        assert client.update_document_metadata.call_count == 3

    def test_skips_documents_without_integer_id(self):
        client = MagicMock()
        docs = [
            {"id": "not-an-int", "tags": [50]},
            {"tags": [50]},  # no id at all
            {"id": None, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=True,
        )

        assert result == 0
        client.update_document_metadata.assert_not_called()

    def test_returns_count_of_recovered_documents(self):
        client = MagicMock()
        docs = [
            {"id": 1, "tags": [50]},
            {"id": 2, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=True,
        )

        assert result == 2


class TestStaleLockRecoveryFlag:
    """The STALE_LOCK_RECOVERY flag gates the startup sweep."""

    def test_disabled_flag_skips_the_sweep_entirely(self):
        # A multi-replica deployment disables the sweep so a restarting replica
        # never steals a peer's live lock. No Paperless call is made.
        client = MagicMock()

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=False,
        )

        assert result == 0
        client.get_documents_by_tag.assert_not_called()
        client.update_document_metadata.assert_not_called()

    def test_enabled_flag_runs_the_sweep(self):
        client = MagicMock()
        client.get_documents_by_tag.return_value = [{"id": 1, "tags": [50]}]

        result = recover_stale_locks(
            client,
            processing_tag_id=50,
            pre_tag_id=10,
            recovery_enabled=True,
        )

        assert result == 1
        client.get_documents_by_tag.assert_called_once_with(50)

    def test_default_resolves_the_flag_from_settings_true(self):
        # When recovery_enabled is left at its default (None), the flag is read
        # from current_settings(). STALE_LOCK_RECOVERY True runs the sweep.
        client = MagicMock()
        client.get_documents_by_tag.return_value = [{"id": 1, "tags": [50]}]
        settings = MagicMock(STALE_LOCK_RECOVERY=True)

        with patch(f"{MODULE}.current_settings", return_value=settings) as cs:
            result = recover_stale_locks(client, processing_tag_id=50, pre_tag_id=10)

        cs.assert_called_once()
        assert result == 1
        client.get_documents_by_tag.assert_called_once_with(50)

    def test_default_resolves_the_flag_from_settings_false(self):
        # STALE_LOCK_RECOVERY False, resolved from settings, skips the sweep.
        client = MagicMock()
        settings = MagicMock(STALE_LOCK_RECOVERY=False)

        with patch(f"{MODULE}.current_settings", return_value=settings) as cs:
            result = recover_stale_locks(client, processing_tag_id=50, pre_tag_id=10)

        cs.assert_called_once()
        assert result == 0
        client.get_documents_by_tag.assert_not_called()

    def test_none_processing_tag_id_never_consults_settings(self):
        # The no-lock-configured early return short-circuits before any settings
        # read, so a daemon with no processing tag pays nothing.
        client = MagicMock()

        with patch(f"{MODULE}.current_settings") as cs:
            result = recover_stale_locks(client, processing_tag_id=None, pre_tag_id=10)

        assert result == 0
        cs.assert_not_called()
