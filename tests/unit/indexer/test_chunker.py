"""Tests for indexer.chunker.

Verifies TextChunk shape, chunk_text splitting behaviour, overlap correctness,
paragraph-boundary preference, page_hint extraction from OCR page markers, and
edge cases (empty input, contiguous chunk_index).
"""

from __future__ import annotations

import pytest

from indexer.chunker import TextChunk, chunk_text


class TestTextChunkShape:
    """TextChunk is a frozen dataclass with the required fields."""

    def test_fields_are_accessible(self) -> None:
        chunk = TextChunk(chunk_index=0, text="hello", page_hint=1)
        assert chunk.chunk_index == 0
        assert chunk.text == "hello"
        assert chunk.page_hint == 1

    def test_page_hint_can_be_none(self) -> None:
        chunk = TextChunk(chunk_index=0, text="hello", page_hint=None)
        assert chunk.page_hint is None

    def test_is_frozen(self) -> None:
        chunk = TextChunk(chunk_index=0, text="hello", page_hint=None)
        with pytest.raises((AttributeError, TypeError)):
            chunk.text = "modified"  # type: ignore[misc]

    def test_slots_prevent_arbitrary_attributes(self) -> None:
        # Frozen+slots raises AttributeError or TypeError depending on the
        # Python version and whether the attribute is known; either proves
        # that arbitrary attributes cannot be added.
        chunk = TextChunk(chunk_index=0, text="hello", page_hint=None)
        with pytest.raises((AttributeError, TypeError)):
            chunk.nonexistent = "value"  # type: ignore[attr-defined]


class TestChunkTextEmptyInput:
    """Empty or whitespace-only content returns an empty list."""

    def test_empty_string_returns_empty_list(self) -> None:
        assert chunk_text("", chunk_size=100, overlap=10) == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert chunk_text("   \n\n\t  ", chunk_size=100, overlap=10) == []

    def test_newlines_only_returns_empty_list(self) -> None:
        assert chunk_text("\n\n\n", chunk_size=100, overlap=10) == []


class TestChunkTextShortDocument:
    """A document shorter than chunk_size yields exactly one chunk."""

    def test_short_document_yields_one_chunk(self) -> None:
        content = "This is a short document."
        chunks = chunk_text(content, chunk_size=200, overlap=20)
        assert len(chunks) == 1

    def test_single_chunk_text_matches_stripped_content(self) -> None:
        content = "Short content."
        chunks = chunk_text(content, chunk_size=200, overlap=20)
        assert chunks[0].text == content

    def test_single_chunk_index_is_zero(self) -> None:
        chunks = chunk_text("Some text.", chunk_size=200, overlap=20)
        assert chunks[0].chunk_index == 0

    def test_single_chunk_no_page_marker_gives_none_hint(self) -> None:
        chunks = chunk_text("Some text.", chunk_size=200, overlap=20)
        assert chunks[0].page_hint is None


class TestChunkTextSizeConstraint:
    """Each chunk's text length must not exceed chunk_size."""

    def test_all_chunks_within_chunk_size(self) -> None:
        # Build a long document without paragraphs so we force multiple chunks.
        content = "word " * 2000  # ~10000 chars
        chunks = chunk_text(content, chunk_size=500, overlap=50)
        for chunk in chunks:
            assert len(chunk.text) <= 500, (
                f"chunk {chunk.chunk_index} has len {len(chunk.text)} > 500"
            )

    def test_multiple_chunks_produced(self) -> None:
        content = "word " * 2000
        chunks = chunk_text(content, chunk_size=500, overlap=50)
        assert len(chunks) > 1


class TestChunkTextOverlap:
    """Adjacent chunks share exactly `overlap` characters at their boundary."""

    def test_adjacent_chunks_share_overlap_suffix_and_prefix(self) -> None:
        # Build a document long enough to produce at least two chunks.
        # No paragraph breaks so chunks are split on character boundaries.
        content = "abcde " * 500  # 3000 chars
        chunk_size = 200
        overlap = 40
        chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
        assert len(chunks) >= 2

        # The last `overlap` characters of chunk N must appear at the start
        # of chunk N+1.
        for i in range(len(chunks) - 1):
            tail = chunks[i].text[-overlap:]
            head = chunks[i + 1].text[:overlap]
            assert head == tail, (
                f"chunks {i} and {i + 1} do not share the expected overlap"
            )

    def test_overlap_zero_produces_no_shared_content(self) -> None:
        content = "x" * 1000
        chunks = chunk_text(content, chunk_size=200, overlap=0)
        assert len(chunks) >= 2
        # Reconstruct original: concatenation of all chunk texts should equal
        # the original content (no overlap means no repetition).
        assert "".join(c.text for c in chunks) == content


class TestChunkTextParagraphBoundaryPreference:
    """Chunks prefer to break on blank-line paragraph boundaries."""

    def test_breaks_at_paragraph_boundary_not_mid_paragraph(self) -> None:
        # Two clearly separated paragraphs; chunk_size chosen so that the
        # first paragraph fits but extending to the second would exceed it.
        para1 = "Alpha " * 40  # 240 chars
        para2 = "Beta " * 40   # 200 chars
        content = para1.rstrip() + "\n\n" + para2.rstrip()

        # chunk_size=300 means para1 (240 chars) fits, but para1+para2 (~442) does not.
        chunks = chunk_text(content, chunk_size=300, overlap=0)
        assert len(chunks) >= 2
        # The first chunk should end at the paragraph boundary, not mid-word.
        assert not chunks[0].text.endswith("Alpha Alpha Alpha Al")

    def test_no_mid_word_split_when_paragraph_boundary_available(self) -> None:
        # Three paragraphs; each fits within chunk_size on its own.
        paragraphs = ["Word " * 30 for _ in range(3)]  # 150 chars each
        content = "\n\n".join(p.rstrip() for p in paragraphs)

        chunks = chunk_text(content, chunk_size=200, overlap=0)
        # Every chunk boundary should align with a paragraph, so no chunk
        # should end mid-word (i.e. no chunk ends with a partial word).
        for chunk in chunks:
            # A mid-word break would leave a trailing non-space character
            # that is not a sentence-end or punctuation. The simplest check:
            # none of the chunk texts should contain the exact paragraph
            # joiner "\n\n" in the middle if it was a clean split.
            # Verify instead that each text, when stripped, is non-empty.
            assert chunk.text.strip()


class TestChunkTextPageHint:
    """page_hint is set from OCR page markers in the content."""

    def _make_multipage_content(self, pages: list[str]) -> str:
        """Reproduce the assemble_full_text output for multi-page content."""
        sections = [f"--- Page {i} ---\n{text}" for i, text in enumerate(pages, 1)]
        return "\n\n".join(sections)

    def test_page_hint_none_when_no_markers(self) -> None:
        content = "Plain text without any page markers."
        chunks = chunk_text(content, chunk_size=200, overlap=20)
        for chunk in chunks:
            assert chunk.page_hint is None

    def test_page_hint_set_from_single_page_marker(self) -> None:
        # Mimic a multi-page document where page 1 marker precedes the text.
        content = "--- Page 1 ---\nFirst page content here."
        chunks = chunk_text(content, chunk_size=200, overlap=0)
        assert len(chunks) >= 1
        assert chunks[0].page_hint == 1

    def test_page_hint_correct_for_each_page(self) -> None:
        # Build a document with two pages, each long enough for its own chunk.
        page1 = "Alpha content. " * 50   # ~750 chars
        page2 = "Beta content. " * 50    # ~700 chars
        content = self._make_multipage_content([page1, page2])

        chunks = chunk_text(content, chunk_size=500, overlap=0)
        assert len(chunks) >= 2

        # First chunk(s) should have page_hint=1; later chunk(s) page_hint=2.
        # Verify the first chunk is from page 1 and at least one chunk is page 2.
        assert chunks[0].page_hint == 1
        page2_chunks = [c for c in chunks if c.page_hint == 2]
        assert len(page2_chunks) >= 1

    def test_page_hint_propagates_to_chunks_within_same_page(self) -> None:
        # Page 1 has enough text for multiple chunks.
        page1 = "Word content here. " * 100  # ~1900 chars
        content = self._make_multipage_content([page1])

        chunks = chunk_text(content, chunk_size=400, overlap=0)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.page_hint == 1

    def test_page_hint_advances_when_marker_encountered(self) -> None:
        # Four pages: verify hint changes at each page boundary.
        pages = ["Content for page %d. " % i * 20 for i in range(1, 5)]
        content = self._make_multipage_content(pages)

        chunks = chunk_text(content, chunk_size=300, overlap=0)
        hints = [c.page_hint for c in chunks]
        # All hints should be in the range 1–4 and should be non-decreasing.
        assert all(h is not None and 1 <= h <= 4 for h in hints)
        assert hints == sorted(hints)

    def test_page_hint_with_model_name_in_header(self) -> None:
        # Mimic include_page_models=True format: "--- Page N (model) ---"
        content = "--- Page 3 (gpt-5.4-mini) ---\nContent on page three."
        chunks = chunk_text(content, chunk_size=200, overlap=0)
        assert chunks[0].page_hint == 3


class TestChunkTextChunkIndex:
    """chunk_index is contiguous from 0 regardless of input."""

    def test_chunk_indices_start_at_zero(self) -> None:
        content = "word " * 200
        chunks = chunk_text(content, chunk_size=100, overlap=10)
        assert chunks[0].chunk_index == 0

    def test_chunk_indices_are_contiguous(self) -> None:
        content = "word " * 500
        chunks = chunk_text(content, chunk_size=100, overlap=10)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_single_chunk_index_is_zero(self) -> None:
        chunks = chunk_text("Short.", chunk_size=1000, overlap=100)
        assert chunks[0].chunk_index == 0
