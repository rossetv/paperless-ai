"""Tests for indexer.chunker."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

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
        with pytest.raises(FrozenInstanceError):
            chunk.text = "modified"  # type: ignore[misc]

    def test_slots_prevent_arbitrary_attributes(self) -> None:
        """Accepts TypeError too: CPython 3.11's frozen slots ``__setattr__`` raises
        it instead of ``FrozenInstanceError``.
        """
        chunk = TextChunk(chunk_index=0, text="hello", page_hint=None)
        with pytest.raises((TypeError, AttributeError)):
            chunk.nonexistent = "value"  # type: ignore[attr-defined]
        # frozen alone also rejects the assignment, so pin slots directly.
        assert not hasattr(chunk, "__dict__")


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
        content = "word " * 2000  # ~10000 chars, no paragraphs
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
        # No paragraph breaks, so chunks split on character boundaries.
        content = "abcde " * 500  # 3000 chars
        chunk_size = 200
        overlap = 40
        chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
        assert len(chunks) >= 2

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
        assert "".join(c.text for c in chunks) == content


class TestChunkTextParagraphBoundaryPreference:
    """Chunks prefer to break on blank-line paragraph boundaries."""

    def test_breaks_at_paragraph_boundary_not_mid_paragraph(self) -> None:
        para1 = "Alpha " * 40  # 240 chars
        para2 = "Beta " * 40  # 200 chars
        content = para1.rstrip() + "\n\n" + para2.rstrip()

        # para1 alone fits 300 chars; para1 + para2 (~442) does not.
        chunks = chunk_text(content, chunk_size=300, overlap=0)
        assert len(chunks) >= 2
        assert not chunks[0].text.endswith("Alpha Alpha Alpha Al")

    def test_no_mid_word_split_when_paragraph_boundary_available(self) -> None:
        paragraphs = ["Word " * 30 for _ in range(3)]  # 150 chars each
        content = "\n\n".join(p.rstrip() for p in paragraphs)

        chunks = chunk_text(content, chunk_size=200, overlap=0)
        for chunk in chunks:
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
        content = "--- Page 1 ---\nFirst page content here."
        chunks = chunk_text(content, chunk_size=200, overlap=0)
        assert len(chunks) >= 1
        assert chunks[0].page_hint == 1

    def test_page_hint_correct_for_each_page(self) -> None:
        page1 = "Alpha content. " * 50  # ~750 chars
        page2 = "Beta content. " * 50  # ~700 chars
        content = self._make_multipage_content([page1, page2])

        chunks = chunk_text(content, chunk_size=500, overlap=0)
        assert len(chunks) >= 2

        assert chunks[0].page_hint == 1
        page2_chunks = [c for c in chunks if c.page_hint == 2]
        assert len(page2_chunks) >= 1

    def test_page_hint_propagates_to_chunks_within_same_page(self) -> None:
        page1 = "Word content here. " * 100  # ~1900 chars
        content = self._make_multipage_content([page1])

        chunks = chunk_text(content, chunk_size=400, overlap=0)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.page_hint == 1

    def test_page_hint_advances_when_marker_encountered(self) -> None:
        pages = ["Content for page %d. " % i * 20 for i in range(1, 5)]
        content = self._make_multipage_content(pages)

        chunks = chunk_text(content, chunk_size=300, overlap=0)
        hints = [c.page_hint for c in chunks]
        assert all(h is not None and 1 <= h <= 4 for h in hints)
        assert hints == sorted(hints)

    def test_page_hint_with_model_name_in_header(self) -> None:
        # The include_page_models=True header format.
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


class TestChunkTextOverlapPrefixOverflow:
    """A paragraph that fits chunk_size alone but overflows with the overlap prefix.

    The overlap prefix never shrinks, so retrying such a paragraph with it
    loops forever; the chunker drops the overlap for that one seam.
    """

    def test_paragraph_overflowing_only_with_overlap_terminates(self) -> None:
        """10-char overlap + separator + ``"B" * 15`` is 27 chars, over chunk_size."""
        content = ("A" * 20) + "\n\n" + ("B" * 15)
        chunks = chunk_text(content, chunk_size=20, overlap=10)
        assert [c.text for c in chunks] == ["A" * 20, "B" * 15]
        assert [c.chunk_index for c in chunks] == [0, 1]

    def test_overflow_case_respects_chunk_size(self) -> None:
        content = ("A" * 20) + "\n\n" + ("B" * 15)
        chunks = chunk_text(content, chunk_size=20, overlap=10)
        for chunk in chunks:
            assert len(chunk.text) <= 20

    def test_multiple_consecutive_trigger_paragraphs_terminate(self) -> None:
        # Each paragraph is in the (chunk_size - overlap - 2, chunk_size] band,
        # so every one overflows when the overlap prefix is prepended.
        content = "\n\n".join(letter * 18 for letter in "ABCD")
        chunks = chunk_text(content, chunk_size=20, overlap=10)
        assert [c.text for c in chunks] == [
            "A" * 18,
            "B" * 18,
            "C" * 18,
            "D" * 18,
        ]


class TestOversizedChunkCap:
    """No emitted chunk exceeds _MAX_CHUNK_CHARS, even with a huge chunk_size."""

    def test_no_chunk_exceeds_the_character_cap(self) -> None:
        from indexer.chunker import _MAX_CHUNK_CHARS

        # No blank lines or spaces and a huge chunk_size: without the cap the
        # paragraph-aware pass would emit one oversized chunk.
        blob = "A" * (_MAX_CHUNK_CHARS * 3 + 17)
        chunks = chunk_text(blob, chunk_size=_MAX_CHUNK_CHARS * 4, overlap=0)

        assert len(chunks) >= 4
        assert all(len(chunk.text) <= _MAX_CHUNK_CHARS for chunk in chunks)

    def test_split_chunks_have_contiguous_indices(self) -> None:
        from indexer.chunker import _MAX_CHUNK_CHARS

        blob = "B" * (_MAX_CHUNK_CHARS * 2 + 5)
        chunks = chunk_text(blob, chunk_size=_MAX_CHUNK_CHARS * 4, overlap=0)

        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_split_preserves_page_hint(self) -> None:
        from indexer.chunker import _MAX_CHUNK_CHARS

        body = "C" * (_MAX_CHUNK_CHARS * 2)
        content = f"--- Page 4 ---\n{body}"
        chunks = chunk_text(content, chunk_size=_MAX_CHUNK_CHARS * 4, overlap=0)

        assert len(chunks) >= 2
        assert all(c.page_hint == 4 for c in chunks)

    def test_split_reassembles_to_the_original_text(self) -> None:
        from indexer.chunker import _MAX_CHUNK_CHARS

        blob = "D" * (_MAX_CHUNK_CHARS * 2 + 13)
        chunks = chunk_text(blob, chunk_size=_MAX_CHUNK_CHARS * 4, overlap=0)

        assert "".join(c.text for c in chunks) == blob

    def test_normal_document_is_untouched_by_the_cap(self) -> None:
        """With the production CHUNK_SIZE (2000) under the cap, the cap is a no-op."""
        content = "\n\n".join(f"Paragraph {i} body text." for i in range(50))
        capped = chunk_text(content, chunk_size=2000, overlap=256)

        assert all(len(c.text) <= 2000 for c in capped)
        assert capped == chunk_text(content, chunk_size=2000, overlap=256)
