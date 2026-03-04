"""Tests for stale processing-lock recovery."""

from unittest.mock import MagicMock, call

from common.stale_lock import recover_stale_locks


def test_noop_when_no_processing_tag():
    """Recovery is skipped when processing_tag_id is None."""
    client = MagicMock()
    result = recover_stale_locks(client, processing_tag_id=None, pre_tag_id=10)
    assert result == 0
    client.get_documents_by_tag.assert_not_called()


def test_noop_when_processing_tag_is_zero():
    client = MagicMock()
    result = recover_stale_locks(client, processing_tag_id=0, pre_tag_id=10)
    assert result == 0


def test_recovers_stale_locked_document():
    """A doc with lock tag but no pre-tag gets re-queued."""
    client = MagicMock()
    # Document has processing tag (99) but NOT the pre-tag (10)
    client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [99, 42]},
    ]

    result = recover_stale_locks(client, processing_tag_id=99, pre_tag_id=10)

    assert result == 1
    client.update_document_metadata.assert_called_once()
    _, kwargs = client.update_document_metadata.call_args
    tags = set(kwargs["tags"])
    assert 10 in tags       # pre-tag re-added
    assert 99 not in tags   # lock tag removed
    assert 42 in tags       # user tag preserved


def test_recovers_document_with_both_tags():
    """A doc with both lock tag AND pre-tag is still recovered (crash before pre-tag removal)."""
    client = MagicMock()
    client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [99, 10]},  # has both
    ]

    result = recover_stale_locks(client, processing_tag_id=99, pre_tag_id=10)

    assert result == 1
    _, kwargs = client.update_document_metadata.call_args
    tags = set(kwargs["tags"])
    assert 10 in tags       # pre-tag preserved
    assert 99 not in tags   # lock tag removed


def test_recovers_multiple_documents():
    client = MagicMock()
    client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [99]},       # stale
        {"id": 2, "tags": [99, 10]},   # stale (crash before pre-tag removal)
        {"id": 3, "tags": [99, 50]},   # stale
    ]

    result = recover_stale_locks(client, processing_tag_id=99, pre_tag_id=10)

    assert result == 3
    assert client.update_document_metadata.call_count == 3


def test_handles_query_failure():
    """If querying fails, return 0 without crashing."""
    client = MagicMock()
    client.get_documents_by_tag.side_effect = RuntimeError("network error")

    result = recover_stale_locks(client, processing_tag_id=99, pre_tag_id=10)

    assert result == 0


def test_handles_update_failure():
    """If updating one doc fails, continue with the rest."""
    client = MagicMock()
    client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [99]},
        {"id": 2, "tags": [99]},
    ]
    client.update_document_metadata.side_effect = [
        RuntimeError("fail"),
        None,
    ]

    result = recover_stale_locks(client, processing_tag_id=99, pre_tag_id=10)

    assert result == 1  # only the second one succeeded
