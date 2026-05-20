"""Tests for ocr.text_assembly."""

from __future__ import annotations

from ocr.text_assembly import OCR_ERROR_MARKER, PageResult, assemble_full_text

class TestOcrErrorMarker:
    def test_value(self):
        assert OCR_ERROR_MARKER == "[OCR ERROR]"

    def test_is_string(self):
        assert isinstance(OCR_ERROR_MARKER, str)

class TestAssembleFullTextSinglePage:
    """Single-page documents should not get page headers."""

    def test_single_page_no_header(self):
        page_results = [PageResult("Hello world", "gpt-5.4-mini")]

        full_text, models = assemble_full_text(1, page_results)

        assert "--- Page" not in full_text
        assert "Hello world" in full_text

    def test_single_page_footer(self):
        page_results = [PageResult("Hello world", "gpt-5.4-mini")]

        full_text, models = assemble_full_text(1, page_results)

        assert full_text.endswith("Transcribed by model: gpt-5.4-mini")

    def test_single_page_models_set(self):
        page_results = [PageResult("Hello world", "gpt-5.4-mini")]

        _, models = assemble_full_text(1, page_results)

        assert models == {"gpt-5.4-mini"}

    def test_single_page_text_and_footer_separated(self):
        page_results = [PageResult("Page text", "model-a")]

        full_text, _ = assemble_full_text(1, page_results)

        # Assert — text and footer separated by double newline
        assert "Page text\n\nTranscribed by model: model-a" == full_text

class TestAssembleFullTextMultiPage:
    """Multi-page documents get "--- Page N ---" headers."""

    def test_multi_page_headers(self):
        page_results = [
            PageResult("Page one text", "model-a"),
            PageResult("Page two text", "model-a"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" in full_text

    def test_multi_page_text_after_header(self):
        page_results = [
            PageResult("First", "m"),
            PageResult("Second", "m"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "--- Page 1 ---\nFirst" in full_text
        assert "--- Page 2 ---\nSecond" in full_text

    def test_multi_page_sections_separated_by_double_newline(self):
        page_results = [
            PageResult("A", "m"),
            PageResult("B", "m"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "--- Page 1 ---\nA\n\n--- Page 2 ---\nB" in full_text

    def test_multi_page_footer(self):
        page_results = [
            PageResult("A", "model-x"),
            PageResult("B", "model-y"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert full_text.endswith("Transcribed by model: model-x, model-y")

    def test_multi_page_models_set(self):
        page_results = [
            PageResult("A", "model-x"),
            PageResult("B", "model-y"),
            PageResult("C", "model-x"),
        ]

        _, models = assemble_full_text(3, page_results)

        assert models == {"model-x", "model-y"}

class TestAssembleFullTextBlankPages:
    """Blank and whitespace-only pages should be skipped."""

    def test_empty_string_skipped(self):
        page_results = [
            PageResult("", "model-a"),
            PageResult("Page two", "model-a"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "--- Page 1 ---" not in full_text
        assert "--- Page 2 ---" in full_text
        assert "Page two" in full_text

    def test_whitespace_only_skipped(self):
        page_results = [
            PageResult("   \n\t  ", "model-a"),
            PageResult("Real text", "model-a"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "--- Page 1 ---" not in full_text
        assert "Real text" in full_text

    def test_all_pages_empty_returns_empty_text(self):
        page_results = [
            PageResult("", "model-a"),
            PageResult("  ", "model-b"),
        ]

        full_text, models = assemble_full_text(2, page_results)

        assert full_text == ""
        assert models == set()

    def test_all_pages_empty_single_page(self):
        page_results = [PageResult("", "model-a")]

        full_text, models = assemble_full_text(1, page_results)

        assert full_text == ""
        assert models == set()

    def test_blank_page_model_not_collected(self):
        # Arrange — blank page with model shouldn't add model to set
        page_results = [
            PageResult("", "model-skipped"),
            PageResult("Real", "model-used"),
        ]

        _, models = assemble_full_text(2, page_results)

        assert "model-skipped" not in models
        assert "model-used" in models

class TestAssembleFullTextIncludePageModels:
    """When include_page_models=True, model name appears in page header."""

    def test_model_in_header(self):
        page_results = [
            PageResult("Text A", "gpt-5"),
            PageResult("Text B", "gpt-5.4-mini"),
        ]

        full_text, _ = assemble_full_text(
            2, page_results, include_page_models=True
        )

        assert "--- Page 1 (gpt-5) ---" in full_text
        assert "--- Page 2 (gpt-5.4-mini) ---" in full_text

    def test_model_not_in_header_by_default(self):
        page_results = [
            PageResult("Text A", "gpt-5"),
            PageResult("Text B", "gpt-5.4-mini"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "(gpt-5)" not in full_text
        assert "(gpt-5.4-mini)" not in full_text

    def test_empty_model_not_in_header(self):
        # Arrange — empty model string should not appear in header
        page_results = [
            PageResult("Text A", ""),
        ]

        full_text, _ = assemble_full_text(
            2, page_results, include_page_models=True
        )

        assert "--- Page 1 ---" in full_text
        assert "()" not in full_text

    def test_include_page_models_single_page_no_header(self):
        # Arrange — single page never gets header even with flag
        page_results = [PageResult("Text", "gpt-5")]

        full_text, _ = assemble_full_text(
            1, page_results, include_page_models=True
        )

        assert "--- Page" not in full_text

class TestAssembleFullTextFooter:
    """Footer lists all models sorted alphabetically."""

    def test_footer_sorted_models(self):
        page_results = [
            PageResult("A", "zebra-model"),
            PageResult("B", "alpha-model"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "Transcribed by model: alpha-model, zebra-model" in full_text

    def test_footer_single_model(self):
        page_results = [
            PageResult("A", "only-model"),
            PageResult("B", "only-model"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        assert "Transcribed by model: only-model" in full_text

    def test_no_footer_when_no_models(self):
        page_results = [
            PageResult("Text", ""),
        ]

        full_text, models = assemble_full_text(1, page_results)

        assert "Transcribed by model" not in full_text
        assert models == set()

    def test_footer_only_when_all_sections_empty_but_models_exist(self):
        # Arrange — all pages are blank, so no sections and no models
        page_results = [PageResult("", "model-a")]

        full_text, models = assemble_full_text(1, page_results)

        # Assert — blank pages skipped, model not collected
        assert full_text == ""
        assert models == set()

class TestAssembleFullTextEdgeCases:
    def test_empty_page_results_list(self):
        page_results: list[PageResult] = []

        full_text, models = assemble_full_text(0, page_results)

        assert full_text == ""
        assert models == set()

    def test_page_count_greater_than_results(self):
        # Arrange — page_count says multi-page but only one result
        page_results = [PageResult("Only page", "m")]

        full_text, _ = assemble_full_text(5, page_results)

        # Assert — still gets header because page_count > 1
        assert "--- Page 1 ---" in full_text

    def test_model_with_empty_string_not_in_set(self):
        page_results = [PageResult("Text", "")]

        _, models = assemble_full_text(1, page_results)

        assert models == set()

    def test_mixed_empty_and_filled_models(self):
        page_results = [
            PageResult("A", ""),
            PageResult("B", "real-model"),
        ]

        full_text, models = assemble_full_text(2, page_results)

        assert models == {"real-model"}
        assert "Transcribed by model: real-model" in full_text

    def test_three_pages_middle_blank(self):
        page_results = [
            PageResult("First", "m1"),
            PageResult("", "m2"),
            PageResult("Third", "m3"),
        ]

        full_text, models = assemble_full_text(3, page_results)

        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" not in full_text
        assert "--- Page 3 ---" in full_text
        assert models == {"m1", "m3"}


class TestPageResult:
    """The PageResult value object is a frozen pair of (text, model)."""

    def test_holds_text_and_model(self):
        page = PageResult("transcribed text", "gpt-5.4-mini")

        assert page.text == "transcribed text"
        assert page.model == "gpt-5.4-mini"

    def test_is_frozen(self):
        page = PageResult("text", "model")

        try:
            page.text = "changed"  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("PageResult should be frozen")

    def test_equality_by_value(self):
        assert PageResult("a", "m") == PageResult("a", "m")
        assert PageResult("a", "m") != PageResult("a", "n")
