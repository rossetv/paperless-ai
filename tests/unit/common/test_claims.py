"""Tests for common.claims."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from common.claims import claim_processing_tag

class TestClaimProcessingTag:
    """Tests for claim_processing_tag()."""

    def test_returns_true_immediately_when_tag_id_is_none(self):
        client = MagicMock()

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=None, purpose="test",
        )

        assert result is True
        client.get_document.assert_not_called()

    def test_successful_claim_refresh_check_patch_verify(self):
        client = MagicMock()
        tag_id = 99
        # Step 1: refresh returns doc without the tag
        # Step 4: verify returns doc with the tag
        client.get_document.side_effect = [
            {"tags": [10, 20]},       # step 1: refresh
            {"tags": [10, 20, 99]},   # step 4: verify
        ]

        result = claim_processing_tag(
            client=client, doc_id=42, tag_id=tag_id, purpose="ocr",
        )

        assert result is True
        assert client.get_document.call_count == 2
        # Step 3: patch was called with updated tags including tag_id
        call_args = client.update_document_metadata.call_args
        assert tag_id in call_args.kwargs["tags"]

    def test_returns_false_when_refresh_fails(self):
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("unreachable")

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=50, purpose="test",
        )

        assert result is False
        client.update_document_metadata.assert_not_called()

    def test_returns_false_when_tag_already_present(self):
        client = MagicMock()
        tag_id = 50
        client.get_document.return_value = {"tags": [10, 50]}  # tag already there

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=tag_id, purpose="test",
        )

        assert result is False
        client.update_document_metadata.assert_not_called()

    def test_returns_false_when_patch_fails(self):
        client = MagicMock()
        client.get_document.return_value = {"tags": [10, 20]}
        client.update_document_metadata.side_effect = ConnectionError("patch fail")

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=50, purpose="test",
        )

        assert result is False

    def test_returns_false_when_verify_refresh_fails(self):
        client = MagicMock()
        client.get_document.side_effect = [
            {"tags": [10, 20]},                    # step 1: refresh OK
            ConnectionError("verify failed"),       # step 4: verify fails
        ]

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=50, purpose="test",
        )

        assert result is False

    def test_returns_false_when_verify_shows_tag_missing(self):
        client = MagicMock()
        client.get_document.side_effect = [
            {"tags": [10, 20]},     # step 1: refresh
            {"tags": [10, 20]},     # step 4: verify — tag disappeared (stale)
        ]

        result = claim_processing_tag(
            client=client, doc_id=1, tag_id=50, purpose="test",
        )

        assert result is False

    def test_logs_correctly_on_successful_claim(self):
        client = MagicMock()
        tag_id = 77
        client.get_document.side_effect = [
            {"tags": [10]},
            {"tags": [10, 77]},
        ]

        with patch("common.claims.log") as mock_log:
            result = claim_processing_tag(
                client=client, doc_id=5, tag_id=tag_id, purpose="ocr",
            )

        assert result is True
        mock_log.info.assert_any_call(
            "Claimed document",
            doc_id=5,
            processing_tag_id=tag_id,
            purpose="ocr",
        )
