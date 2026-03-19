"""Tests for common.content_checks."""

from __future__ import annotations

from PIL import Image

from common.content_checks import contains_redacted_marker, is_error_content
from ocr.provider import is_blank

class TestIsBlank:
    """Tests for is_blank(image, threshold=5)."""

    def test_white_image_returns_true(self):
        """A pure-white image is blank."""
        img = Image.new("L", (100, 100), color=255)
        assert is_blank(img) is True

    def test_rgb_white_image_returns_true(self):
        """A pure-white RGB image is blank (converted to greyscale internally)."""
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        assert is_blank(img) is True

    def test_near_white_image_below_threshold_returns_true(self):
        """An image with a few non-white pixels below threshold is blank."""
        img = Image.new("L", (100, 100), color=255)
        # Place 4 dark pixels (below default threshold of 5)
        for i in range(4):
            img.putpixel((i, 0), 0)
        assert is_blank(img) is True

    def test_non_white_image_returns_false(self):
        """A fully black image is not blank."""
        img = Image.new("L", (100, 100), color=0)
        assert is_blank(img) is False

    def test_image_above_threshold_returns_false(self):
        """An image with non-white pixels above threshold is not blank."""
        img = Image.new("L", (100, 100), color=255)
        # Place 10 dark pixels (above default threshold of 5)
        for i in range(10):
            img.putpixel((i, 0), 0)
        assert is_blank(img) is False

    def test_custom_threshold(self):
        """A custom threshold changes the sensitivity."""
        img = Image.new("L", (100, 100), color=255)
        for i in range(8):
            img.putpixel((i, 0), 0)
        assert is_blank(img, threshold=5) is False
        assert is_blank(img, threshold=10) is True

    def test_grey_image_not_blank(self):
        """A mid-grey image is not blank."""
        img = Image.new("L", (10, 10), color=128)
        assert is_blank(img) is False

class TestContainsRedactedMarker:
    """Tests for contains_redacted_marker(text)."""

    def test_redacted_in_brackets(self):
        assert contains_redacted_marker("[REDACTED]") is True

    def test_name_redacted_in_brackets(self):
        assert contains_redacted_marker("[NAME REDACTED]") is True

    def test_redacted_address_in_brackets(self):
        assert contains_redacted_marker("[REDACTED ADDRESS]") is True

    def test_redacted_without_brackets_returns_false(self):
        assert contains_redacted_marker("REDACTED") is False

    def test_empty_string_returns_false(self):
        assert contains_redacted_marker("") is False

    def test_case_insensitive(self):
        assert contains_redacted_marker("[redacted]") is True
        assert contains_redacted_marker("[Redacted Name]") is True

    def test_embedded_in_longer_text(self):
        text = "Dear customer, the name is [REDACTED] for privacy."
        assert contains_redacted_marker(text) is True

    def test_no_marker_returns_false(self):
        assert contains_redacted_marker("This is normal text.") is False

class TestIsErrorContent:
    """Tests for is_error_content(text, error_phrases)."""

    def test_text_with_refusal_phrase(self):
        phrases = ("i can't assist with that",)
        text = "I can't assist with that request."
        assert is_error_content(text, phrases) is True

    def test_text_with_redaction_marker(self):
        text = "Content: [REDACTED]"
        assert is_error_content(text, ()) is True

    def test_clean_text_returns_false(self):
        phrases = ("i can't assist with that",)
        text = "This is a normal document about taxes."
        assert is_error_content(text, phrases) is False

    def test_case_insensitive_phrase_matching(self):
        phrases = ("sorry, i cannot help",)
        text = "SORRY, I CANNOT HELP with this request."
        assert is_error_content(text, phrases) is True

    def test_empty_text_returns_false(self):
        phrases = ("error phrase",)
        assert is_error_content("", phrases) is False

    def test_empty_phrases_only_checks_redaction(self):
        assert is_error_content("Normal text", ()) is False
        assert is_error_content("[REDACTED]", ()) is True

    def test_multiple_phrases_any_match(self):
        phrases = ("phrase one", "phrase two")
        assert is_error_content("This has phrase two in it.", phrases) is True
