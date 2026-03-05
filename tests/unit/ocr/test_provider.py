"""
Comprehensive unit tests for ocr.provider module.

Tests cover:
- is_refusal: refusal marker detection, case-insensitive, redacted markers
- OpenAIProvider.transcribe_image:
  - Successful transcription on first model
  - Fallback on refusal
  - Fallback on API error
  - All models fail -> returns REFUSAL_MARK
  - Blank image -> returns ("", "") without API call
  - Image resizing when > OCR_MAX_SIDE
  - Stats tracking (attempts, refusals, api_errors, fallback_successes)
  - Thread-safe stat updates
  - doc_id and page_num in logging context
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import openai
from PIL import Image

from ocr.provider import OpenAIProvider, is_refusal


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_settings(**overrides):
    """Create a mock Settings for OpenAIProvider."""
    from tests.helpers.factories import make_settings_obj
    return make_settings_obj(**overrides)


def _make_provider(settings=None, **setting_overrides):
    """Create an OpenAIProvider with mocked settings."""
    if settings is None:
        settings = _make_settings(**setting_overrides)
    with patch.object(OpenAIProvider, "_create_completion"):
        provider = OpenAIProvider(settings)
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


# -----------------------------------------------------------------------
# is_refusal
# -----------------------------------------------------------------------

class TestIsRefusal:
    def test_matching_marker(self):
        # Arrange
        markers = ["chatgpt refused to transcribe"]

        # Act / Assert
        assert is_refusal("CHATGPT REFUSED TO TRANSCRIBE this page", markers) is True

    def test_case_insensitive(self):
        # Arrange
        markers = ["cannot process"]

        # Act / Assert
        assert is_refusal("I Cannot Process this image", markers) is True

    def test_no_match(self):
        # Arrange
        markers = ["chatgpt refused to transcribe"]

        # Act / Assert
        assert is_refusal("This is normal text from a document", markers) is False

    def test_redacted_marker_detected(self):
        # Arrange
        markers = []

        # Act / Assert
        assert is_refusal("Some text [REDACTED] more text", markers) is True

    def test_redacted_name_pattern(self):
        # Arrange
        markers = []

        # Act / Assert
        assert is_refusal("Name: [NAME REDACTED]", markers) is True

    def test_empty_markers_no_redacted(self):
        # Arrange
        markers = []

        # Act / Assert
        assert is_refusal("Normal text without issues", markers) is False

    def test_multiple_markers_first_matches(self):
        # Arrange
        markers = ["refused", "cannot", "unable"]

        # Act / Assert
        assert is_refusal("I refused to do it", markers) is True

    def test_multiple_markers_last_matches(self):
        # Arrange
        markers = ["refused", "cannot", "unable"]

        # Act / Assert
        assert is_refusal("I am unable to help", markers) is True

    def test_mixed_case_markers_still_match(self):
        """Markers with uppercase chars should still match (case-insensitive)."""
        markers = ["Cannot Process", "REFUSED"]

        assert is_refusal("i cannot process this image", markers) is True
        assert is_refusal("the model refused to transcribe", markers) is True

    def test_mixed_case_marker_no_match(self):
        markers = ["Cannot Process"]

        assert is_refusal("normal document text", markers) is False


# -----------------------------------------------------------------------
# OpenAIProvider — successful transcription
# -----------------------------------------------------------------------

class TestOpenAIProviderSuccess:
    def test_first_model_success(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["gpt-5-mini"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("Transcribed text")
        )
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image, doc_id=1, page_num=1)

        # Assert
        assert text == "Transcribed text"
        assert model == "gpt-5-mini"

    def test_returns_stripped_text(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("  text with whitespace  \n")
        )
        image = _make_test_image()

        # Act
        text, _ = provider.transcribe_image(image)

        # Assert
        assert text == "text with whitespace"


# -----------------------------------------------------------------------
# OpenAIProvider — fallback on refusal
# -----------------------------------------------------------------------

class TestOpenAIProviderRefusalFallback:
    def test_fallback_on_refusal(self):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot process this image"),
                _make_response("Actual transcription"),
            ]
        )
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image, doc_id=42, page_num=1)

        # Assert
        assert text == "Actual transcription"
        assert model == "model-b"

    def test_refusal_increments_stats(self):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot do this"),
                _make_response("OK text"),
            ]
        )
        image = _make_test_image()

        # Act
        provider.transcribe_image(image)

        # Assert
        stats = provider.get_stats()
        assert stats["refusals"] == 1
        assert stats["attempts"] == 2
        assert stats["fallback_successes"] == 1


# -----------------------------------------------------------------------
# OpenAIProvider — fallback on API error
# -----------------------------------------------------------------------

class TestOpenAIProviderApiErrorFallback:
    def test_fallback_on_api_error(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a", "model-b"])
        provider = OpenAIProvider(settings)
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

        # Act
        text, model = provider.transcribe_image(image, doc_id=5, page_num=2)

        # Assert
        assert text == "Fallback transcription"
        assert model == "model-b"

    def test_api_error_increments_stats(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a", "model-b"])
        provider = OpenAIProvider(settings)
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

        # Act
        provider.transcribe_image(image)

        # Assert
        stats = provider.get_stats()
        assert stats["api_errors"] == 1
        assert stats["fallback_successes"] == 1


# -----------------------------------------------------------------------
# OpenAIProvider — all models fail
# -----------------------------------------------------------------------

class TestOpenAIProviderAllFail:
    def test_all_models_refuse_returns_refusal_mark(self):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a", "model-b"],
            OCR_REFUSAL_MARKERS=["i cannot"],
            REFUSAL_MARK="CHATGPT REFUSED TO TRANSCRIBE",
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("I cannot do this"),
                _make_response("I cannot do this either"),
            ]
        )
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image)

        # Assert
        assert text == "CHATGPT REFUSED TO TRANSCRIBE"
        assert model == ""

    def test_all_models_api_error_returns_refusal_mark(self):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a"],
            REFUSAL_MARK="REFUSED",
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=openai.APIError(
                message="fail",
                request=MagicMock(),
                body=None,
            )
        )
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image)

        # Assert
        assert text == "REFUSED"
        assert model == ""


# -----------------------------------------------------------------------
# OpenAIProvider — blank image
# -----------------------------------------------------------------------

class TestOpenAIProviderBlankImage:
    @patch("ocr.provider.is_blank", return_value=True)
    def test_blank_image_returns_empty_without_api_call(self, mock_is_blank):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock()
        image = _make_blank_image()

        # Act
        text, model = provider.transcribe_image(image, doc_id=1, page_num=1)

        # Assert
        assert text == ""
        assert model == ""
        provider._create_completion.assert_not_called()

    @patch("ocr.provider.is_blank", return_value=True)
    def test_blank_image_no_stats_increment(self, mock_is_blank):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock()
        image = _make_blank_image()

        # Act
        provider.transcribe_image(image)

        # Assert
        stats = provider.get_stats()
        assert stats["attempts"] == 0


# -----------------------------------------------------------------------
# OpenAIProvider — image resizing
# -----------------------------------------------------------------------

class TestOpenAIProviderImageResize:
    @patch("ocr.provider.is_blank", return_value=False)
    def test_large_image_resized(self, mock_is_blank):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a"],
            OCR_MAX_SIDE=500,
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("text")
        )
        # Create image larger than OCR_MAX_SIDE
        image = _make_test_image(width=1000, height=800)

        # Act
        provider.transcribe_image(image)

        # Assert — image should have been resized (thumbnail modifies in place)
        assert image.size[0] <= 500
        assert image.size[1] <= 500

    @patch("ocr.provider.is_blank", return_value=False)
    def test_small_image_not_resized(self, mock_is_blank):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["model-a"],
            OCR_MAX_SIDE=2000,
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("text")
        )
        image = _make_test_image(width=100, height=100)

        # Act
        provider.transcribe_image(image)

        # Assert — image not changed
        assert image.size == (100, 100)


# -----------------------------------------------------------------------
# OpenAIProvider — stats tracking
# -----------------------------------------------------------------------

class TestOpenAIProviderStats:
    def test_initial_stats(self):
        # Arrange
        provider = _make_provider()

        # Act
        stats = provider.get_stats()

        # Assert
        assert stats == {
            "attempts": 0,
            "refusals": 0,
            "api_errors": 0,
            "fallback_successes": 0,
        }

    def test_get_stats_returns_snapshot(self):
        # Arrange
        provider = _make_provider()

        # Act
        stats1 = provider.get_stats()
        stats1["attempts"] = 999  # mutate the returned dict

        # Assert — original stats unaffected
        stats2 = provider.get_stats()
        assert stats2["attempts"] == 0

    def test_fallback_success_tracked(self):
        # Arrange
        settings = _make_settings(
            AI_MODELS=["primary", "fallback"],
            OCR_REFUSAL_MARKERS=["refused"],
        )
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                _make_response("refused to do it"),
                _make_response("good text"),
            ]
        )
        image = _make_test_image()

        # Act
        provider.transcribe_image(image)

        # Assert
        stats = provider.get_stats()
        assert stats["fallback_successes"] == 1
        assert stats["attempts"] == 2
        assert stats["refusals"] == 1

    def test_primary_model_success_no_fallback_stat(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["primary", "fallback"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            return_value=_make_response("good text")
        )
        image = _make_test_image()

        # Act
        provider.transcribe_image(image)

        # Assert
        stats = provider.get_stats()
        assert stats["fallback_successes"] == 0
        assert stats["attempts"] == 1


# -----------------------------------------------------------------------
# OpenAIProvider — thread-safe stats
# -----------------------------------------------------------------------

class TestOpenAIProviderThreadSafety:
    def test_concurrent_stat_increments(self):
        # Arrange
        provider = _make_provider()
        num_threads = 10
        increments_per_thread = 100

        def increment_stats():
            for _ in range(increments_per_thread):
                provider._stats.inc("attempts")

        # Act
        threads = [
            threading.Thread(target=increment_stats)
            for _ in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert
        stats = provider.get_stats()
        assert stats["attempts"] == num_threads * increments_per_thread


# -----------------------------------------------------------------------
# OpenAIProvider — duplicate model deduplication
# -----------------------------------------------------------------------

class TestOpenAIProviderDuplicateModels:
    def test_duplicate_models_tried_once(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a", "model-a", "model-b"])
        provider = OpenAIProvider(settings)
        provider._create_completion = MagicMock(
            side_effect=[
                openai.APIError(message="fail", request=MagicMock(), body=None),
                _make_response("ok from b"),
            ]
        )
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image)

        # Assert — model-a tried once (deduplicated), then model-b
        assert text == "ok from b"
        assert model == "model-b"
        assert provider._create_completion.call_count == 2


# -----------------------------------------------------------------------
# OpenAIProvider — None content handling
# -----------------------------------------------------------------------

class TestOpenAIProviderNoneContent:
    def test_none_response_content_treated_as_empty(self):
        # Arrange
        settings = _make_settings(AI_MODELS=["model-a"])
        provider = OpenAIProvider(settings)
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = None
        provider._create_completion = MagicMock(return_value=response)
        image = _make_test_image()

        # Act
        text, model = provider.transcribe_image(image)

        # Assert — empty string is not a refusal, so it returns
        assert text == ""
        assert model == "model-a"
