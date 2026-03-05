"""Tests for common.document_iter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.document_iter import iter_documents_by_pipeline_tag


def _make_mock_client(documents: list[dict]) -> MagicMock:
    client = MagicMock()
    client.get_documents_by_tag.return_value = documents
    return client


class TestYieldsValidDocuments:
    def test_yields_valid_document(self):
        doc = {"id": 1, "title": "Test", "tags": [443]}
        client = _make_mock_client([doc])

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=None, context="test",
        ))

        assert result == [doc]

    def test_yields_multiple_documents(self):
        docs = [
            {"id": 1, "title": "A", "tags": [443]},
            {"id": 2, "title": "B", "tags": [443]},
        ]
        client = _make_mock_client(docs)

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=None, context="test",
        ))

        assert len(result) == 2


class TestSkipsInvalidIds:
    def test_skips_none_id(self):
        client = _make_mock_client([{"id": None, "tags": [443]}])

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=None, context="test",
        ))

        assert result == []

    def test_skips_string_id(self):
        client = _make_mock_client([{"id": "abc", "tags": [443]}])

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=None, context="test",
        ))

        assert result == []


class TestSkipsProcessedDocs:
    def test_skips_doc_with_post_tag(self):
        client = _make_mock_client([{"id": 1, "tags": [443, 444]}])

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=None, context="test",
        ))

        assert result == []

    @patch("common.document_iter.remove_stale_queue_tag")
    def test_removes_stale_pre_tag(self, mock_remove):
        client = _make_mock_client([{"id": 1, "tags": [443, 444]}])

        list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=999, context="test",
        ))

        mock_remove.assert_called_once()


class TestSkipsClaimedDocs:
    def test_skips_doc_with_processing_tag(self):
        client = _make_mock_client([{"id": 1, "tags": [443, 999]}])

        result = list(iter_documents_by_pipeline_tag(
            client, pre_tag_id=443, post_tag_id=444,
            processing_tag_id=999, context="test",
        ))

        assert result == []
