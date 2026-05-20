"""Tests for common.per_document."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from common.per_document import run_per_document
from tests.helpers.factories import make_document, make_settings_obj


class TestRunPerDocument:
    """run_per_document owns the per-thread Paperless client lifecycle."""

    @patch("common.per_document.PaperlessClient")
    def test_constructs_client_with_settings(self, mock_client_cls):
        settings = make_settings_obj()
        doc = make_document()
        build_processor = MagicMock(return_value=MagicMock())

        run_per_document(doc, settings, build_processor)

        mock_client_cls.assert_called_once_with(settings)

    @patch("common.per_document.PaperlessClient")
    def test_passes_doc_and_client_to_builder(self, mock_client_cls):
        settings = make_settings_obj()
        doc = make_document(id=7)
        client_instance = mock_client_cls.return_value
        build_processor = MagicMock(return_value=MagicMock())

        run_per_document(doc, settings, build_processor)

        build_processor.assert_called_once_with(doc, client_instance)

    @patch("common.per_document.PaperlessClient")
    def test_runs_the_built_processor(self, mock_client_cls):
        settings = make_settings_obj()
        processor = MagicMock()
        build_processor = MagicMock(return_value=processor)

        run_per_document(make_document(), settings, build_processor)

        processor.process.assert_called_once_with()

    @patch("common.per_document.PaperlessClient")
    def test_closes_client_after_success(self, mock_client_cls):
        settings = make_settings_obj()
        client_instance = mock_client_cls.return_value

        run_per_document(
            make_document(), settings, lambda d, c: MagicMock()
        )

        client_instance.close.assert_called_once()

    @patch("common.per_document.PaperlessClient")
    def test_closes_client_even_when_processing_raises(self, mock_client_cls):
        settings = make_settings_obj()
        client_instance = mock_client_cls.return_value
        processor = MagicMock()
        processor.process.side_effect = RuntimeError("processing boom")

        with pytest.raises(RuntimeError, match="processing boom"):
            run_per_document(
                make_document(), settings, lambda d, c: processor
            )

        client_instance.close.assert_called_once()

    @patch("common.per_document.PaperlessClient")
    def test_closes_client_even_when_builder_raises(self, mock_client_cls):
        settings = make_settings_obj()
        client_instance = mock_client_cls.return_value

        def failing_builder(doc, client):
            raise ValueError("builder boom")

        with pytest.raises(ValueError, match="builder boom"):
            run_per_document(make_document(), settings, failing_builder)

        client_instance.close.assert_called_once()
