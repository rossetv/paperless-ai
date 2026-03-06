"""Tests for ocr.provider."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import openai
from PIL import Image

from common.utils import is_error_content
from ocr.provider import OcrProvider

def _make_settings(**overrides):
    """Create a mock Settings for OcrProvider."""
    from tests.helpers.factories import make_settings_obj
    return make_settings_obj(**overrides)

def _make_provider(settings=None, **setting_overrides):
    """Create an OcrProvider with mocked settings."""
    if settings is None:
        settings = _make_settings(**setting_overrides)
    with patch.object(OcrProvider, "_create_completion"):
        provider = OcrProvider(settings)
    return provider

def _make_response(text: str) -> MagicMock:
    """Create a mock OpenAI chat completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = text
    return response

def _make_test_image(width: int = 100, height: int = 100) -> Image.Image:
    """Create a non-blank test image."""
    img = Image.new("RGB", (width, height), color="red")
    return img

def _make_blank_image() -> Image.Image:
    """Create a blank (all-white) image."""
    return Image.new("RGB", (100, 100), color="white")

class TestIsRefusal:
    def test_matching_marker(self):
        markers = ["chatgpt refused to transcribe"]

        assert is_error_content("CHATGPT REFUSED TO TRANSCRIBE this page", markers) is True

    def test_case_insensitive(self):
        markers = ["cannot process"]

        assert is_error_content("I Cannot Process this image", markers) is True

    def test_no_match(self):
        markers = ["chatgpt refused to transcribe"]

        assert is_error_content("This is normal text from a document", markers) is False

    def test_redacted_marker_detected(self):
        markers = []

        assert is_error_content("Some text [REDACTED] more text", markers) is True

    def test_redacted_name_pattern(self):
        markers = []

        assert is_error_content("Name: [NAME REDACTED]", markers) is True

    def test_empty_markers_no_redacted(self):
        markers = []

        assert is_error_content("Normal text without issues", markers) is False

    def test_multiple_markers_first_matches(self):
        markers = ["refused", "cannot", "unable"]

        assert is_error_content("I refused to do it", markers) is True

    def test_multiple_markers_last_matches(self):
        markers = ["refused", "cannot", "unable"]

        assert is_error_content("I am unable to help", markers) is True

    def test_mixed_case_markers_still_match(self):
        """Markers with uppercase chars should still match (case-insensitive)."""
        markers = ["Cannot Process", "REFUSED"]

        assert is_error_content("i cannot process this image", markers) is True
        assert is_error_content("the model refused to transcribe", markers) is True

    def test_mixed_case_marker_no_match(self):
        markers = ["Cannot Process"]

        assert is_error_content("normal document text", markers) is False

class TestOcrProviderSuccess:
    def test_first_model_success(self):
        settings = _make_settings(AI_MODELS=["gpt-5-mini"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("Transcribed text")
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image, doc_id=1, page_num=1)

        assert text == "Transcribed text"
        assert model == "gpt-5-mini"

    def test_returns_stripped_text(self):
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("  text with whitespace  \n")
        )
        image = _make_test_image()

        text, _ = provider.transcribe_image(image)

        assert text == "text with whitespace"

class TestOcrProviderRefusalFallback:
    def test_fallback_on_refusal(self):
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot process this image"),
                _make_response("Actual transcription"),
            ]
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image, doc_id=42, page_num=1)

        assert text == "Actual transcription"
        assert model == "model-b"

    def test_refusal_increments_stats(self):
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot do this"),
                _make_response("OK text"),
            ]
        )
        image = _make_test_image()

        provider.transcribe_image(image)

        stats = provider.get_stats()
        assert stats["refusals"] == 1
        assert stats["attempts"] == 2
        assert stats["fallback_successes"] == 1

class TestOcrProviderApiErrorFallback:
    def test_fallback_on_api_error(self):
        settings = _make_settings(AI_MODELS=["model-a", "model-b"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                openai.APIError(
                    message="Server error",
                    request=MagicMock(),
                    body=None,
                ),
                _make_response("Fallback transcription"),
            ]
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image, doc_id=5, page_num=2)

        assert text == "Fallback transcription"
        assert model == "model-b"

    def test_api_error_increments_stats(self):
        settings = _make_settings(AI_MODELS=["model-a", "model-b"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                openai.APIError(
                    message="err",
                    request=MagicMock(),
                    body=None,
                ),
                _make_response("OK"),
            ]
        )
        image = _make_test_image()

        provider.transcribe_image(image)

        stats = provider.get_stats()
        assert stats["api_errors"] == 1
        assert stats["fallback_successes"] == 1

class TestOcrProviderAllFail:
    def test_all_models_refuse_returns_refusal_mark(self):
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
            REFUSAL_MARK="CHATGPT REFUSED TO TRANSCRIBE",
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot do this"),
                _make_response("I cannot do this either"),
            ]
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image)

        assert text == "CHATGPT REFUSED TO TRANSCRIBE"
        assert model == ""

    def test_all_models_api_error_returns_refusal_mark(self):
        settings = _make_settings(
            AI_MODELS=["model-a"],
            REFUSAL_MARK="REFUSED",
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=openai.APIError(
                message="fail",
                request=MagicMock(),
                body=None,
            )
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image)

        assert text == "REFUSED"
        assert model == ""

class TestOcrProviderBlankImage:
    @patch("ocr.provider.is_blank", return_value=True)
    def test_blank_image_returns_empty_without_api_call(self, mock_is_blank):
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock()
        image = _make_blank_image()

        text, model = provider.transcribe_image(image, doc_id=1, page_num=1)

        assert text == ""
        assert model == ""
        provider._create_completion.assert_not_called()

    @patch("ocr.provider.is_blank", return_value=True)
    def test_blank_image_no_stats_increment(self, mock_is_blank):
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock()
        image = _make_blank_image()

        provider.transcribe_image(image)

        stats = provider.get_stats()
        assert stats["attempts"] == 0

class TestOcrProviderImageResize:
    @patch("ocr.provider.is_blank", return_value=False)
    def test_large_image_resized(self, mock_is_blank):
        settings = _make_settings(
            AI_MODELS=["model-a"],
            OCR_MAX_SIDE=500,
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("text")
        )
        # Create image larger than OCR_MAX_SIDE
        image = _make_test_image(width=1000, height=800)

        provider.transcribe_image(image)

        # Assert — the caller's image must NOT be mutated (copy is made internally)
        assert image.size == (1000, 800)

    @patch("ocr.provider.is_blank", return_value=False)
    def test_small_image_not_resized(self, mock_is_blank):
        settings = _make_settings(
            AI_MODELS=["model-a"],
            OCR_MAX_SIDE=2000,
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("text")
        )
        image = _make_test_image(width=100, height=100)

        provider.transcribe_image(image)

        assert image.size == (100, 100)

class TestOcrProviderStats:
    def test_initial_stats(self):
        provider = _make_provider()

        stats = provider.get_stats()

        assert stats == {
            "attempts": 0,
            "refusals": 0,
            "api_errors": 0,
            "fallback_successes": 0,
        }

    def test_get_stats_returns_snapshot(self):
        provider = _make_provider()

        stats1 = provider.get_stats()
        stats1["attempts"] = 999  # mutate the returned dict

        stats2 = provider.get_stats()
        assert stats2["attempts"] == 0

    def test_fallback_success_tracked(self):
        settings = _make_settings(
            AI_MODELS=["primary", "fallback"],
            OCR_REFUSAL_MARKERS=["refused"],
        )
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("refused to do it"),
                _make_response("good text"),
            ]
        )
        image = _make_test_image()

        provider.transcribe_image(image)

        stats = provider.get_stats()
        assert stats["fallback_successes"] == 1
        assert stats["attempts"] == 2
        assert stats["refusals"] == 1

    def test_primary_model_success_no_fallback_stat(self):
        settings = _make_settings(AI_MODELS=["primary", "fallback"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("good text")
        )
        image = _make_test_image()

        provider.transcribe_image(image)

        stats = provider.get_stats()
        assert stats["fallback_successes"] == 0
        assert stats["attempts"] == 1

class TestOcrProviderThreadSafety:
    def test_concurrent_stat_increments(self):
        provider = _make_provider()
        num_threads = 10
        increments_per_thread = 100

        def increment_stats():
            for _ in range(increments_per_thread):
                provider._stats.inc("attempts")

        threads = [
            threading.Thread(target=increment_stats)
            for _ in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = provider.get_stats()
        assert stats["attempts"] == num_threads * increments_per_thread

class TestOcrProviderDuplicateModels:
    def test_duplicate_models_tried_once(self):
        settings = _make_settings(AI_MODELS=["model-a", "model-a", "model-b"])
        provider = OcrProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                openai.APIError(message="fail", request=MagicMock(), body=None),
                _make_response("ok from b"),
            ]
        )
        image = _make_test_image()

        text, model = provider.transcribe_image(image)

        # Assert — model-a tried once (deduplicated), then model-b
        assert text == "ok from b"
        assert model == "model-b"
        assert provider._create_completion.call_count == 2

class TestOcrProviderNoneContent:
    def test_none_response_content_treated_as_empty(self):
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OcrProvider(settings)
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = None
        provider._create_completion = MagicMock(return_value=response)
        image = _make_test_image()

        text, model = provider.transcribe_image(image)

        # Assert — empty string is not a refusal, so it returns
        assert text == ""
        assert model == "model-a"
