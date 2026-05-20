"""Splits OCR document text into overlapping TextChunks for embedding.

Chunks are character-based windows of at most ``chunk_size`` characters with
``overlap`` characters of shared content between adjacent windows.  The splitter
prefers to break on paragraph boundaries (blank lines) rather than mid-word.

Page hints are derived from the OCR page-marker format produced by
``ocr.text_assembly.assemble_full_text``:

    --- Page N ---
    <page text>

or (when ``include_page_models=True``):

    --- Page N (model-name) ---
    <page text>

The page number in effect at a chunk's start position is stored as
``page_hint``; it is ``None`` when no page marker precedes the chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches the OCR page-marker lines produced by ocr.text_assembly:
#   "--- Page N ---"  or  "--- Page N (model-name) ---"
# Capture group 1 is the 1-based page number.
_PAGE_MARKER_RE = re.compile(r"^--- Page (\d+)(?: \([^)]+\))? ---$")


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A single chunk of document text, ready for embedding.

    Attributes:
        chunk_index: Zero-based position of this chunk within the document.
        text: The chunk text (at most ``chunk_size`` characters).
        page_hint: The OCR page number in effect at the chunk's start, or
            ``None`` when no page marker precedes the chunk.
    """

    chunk_index: int
    text: str
    page_hint: int | None


def chunk_text(
    content: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    """Split *content* into overlapping TextChunks.

    The algorithm:
    1. Walk the content line by line, tracking the current page number from
       OCR page markers.  Each non-marker line is appended to a working
       paragraph buffer.  A blank line triggers a paragraph flush.
    2. Paragraphs are accumulated into a running window.  When adding the next
       paragraph would push the window past ``chunk_size``, the current window
       is emitted as a chunk and a new window is started from the last
       ``overlap`` characters of the previous chunk (the overlap tail).
    3. After all paragraphs are consumed, any remaining window is emitted.

    Empty or whitespace-only *content* returns ``[]``.

    Args:
        content: The full OCR text, possibly containing ``--- Page N ---`` markers.
        chunk_size: Maximum character length of each chunk's text.
        overlap: Number of characters shared between the end of chunk N and
            the start of chunk N+1.

    Returns:
        An ordered list of :class:`TextChunk` instances with contiguous
        ``chunk_index`` values starting from 0.
    """
    if not content.strip():
        return []

    # --- Pass 1: parse lines into (page_number | None, paragraph_text) pairs.
    # A paragraph is a run of non-blank lines; blank lines are separators.
    paragraphs: list[tuple[int | None, str]] = []
    current_page: int | None = None
    paragraph_lines: list[str] = []
    # page number at the start of the current paragraph buffer
    paragraph_page: int | None = None

    def _flush_paragraph(
        lines: list[str], page: int | None, dest: list[tuple[int | None, str]]
    ) -> None:
        text = "\n".join(lines).strip()
        if text:
            dest.append((page, text))

    for raw_line in content.splitlines():
        marker_match = _PAGE_MARKER_RE.match(raw_line)
        if marker_match:
            # Flush the current paragraph before advancing the page counter.
            _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)
            paragraph_lines = []
            current_page = int(marker_match.group(1))
            paragraph_page = current_page
            continue

        if raw_line.strip() == "":
            # Blank line — paragraph boundary.
            _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)
            paragraph_lines = []
            paragraph_page = current_page
        else:
            if not paragraph_lines:
                # Record the page number at the start of this new paragraph.
                paragraph_page = current_page
            paragraph_lines.append(raw_line)

    # Flush any remaining paragraph.
    _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)

    if not paragraphs:
        return []

    # --- Pass 2: assemble paragraphs into chunks.
    chunks: list[TextChunk] = []

    # The overlap tail carried forward from the previous chunk.
    overlap_prefix: str = ""
    # Page hint for the current window (set from the overlap tail's page, or
    # the first paragraph added to this window).
    window_page: int | None = None
    window_text: str = ""

    # When the overlap prefix is non-empty we need to initialise the window
    # page from the previous chunk.  We track the previous chunk's page hint
    # to propagate it into the overlap prefix of the next window.
    prev_chunk_page: int | None = None

    def _emit_chunk(text: str, page: int | None, index: int) -> TextChunk:
        return TextChunk(chunk_index=index, text=text, page_hint=page)

    paragraph_idx = 0
    while paragraph_idx < len(paragraphs):
        para_page, para_text = paragraphs[paragraph_idx]

        # Start a new window from the overlap tail of the previous chunk.
        if window_text == "" and overlap_prefix:
            window_text = overlap_prefix
            # The overlap tail was part of the previous chunk whose page hint
            # we recorded; keep that page hint until a new paragraph with a
            # different (non-None) page advances it.
            window_page = prev_chunk_page

        # Determine the separator between the current window content and the
        # incoming paragraph (double newline for readability).
        separator = "\n\n" if window_text else ""
        candidate = window_text + separator + para_text

        if len(candidate) <= chunk_size:
            # Paragraph fits — add it to the current window.
            window_text = candidate
            if window_page is None and para_page is not None:
                window_page = para_page
            paragraph_idx += 1
        else:
            # Paragraph would overflow.
            if window_text:
                # Emit the current window as a chunk.
                prev_chunk_page = window_page
                chunks.append(_emit_chunk(window_text, window_page, len(chunks)))
                overlap_prefix = window_text[-overlap:] if overlap > 0 else ""
                window_text = ""
                window_page = None
                # Do NOT advance paragraph_idx — retry this paragraph in the
                # new window.
            else:
                # The paragraph itself is larger than chunk_size; we must emit
                # it in character-sized slices to honour the constraint.  Every
                # slice carries the paragraph's own page hint.
                start = 0
                while start < len(para_text):
                    slice_text = para_text[start : start + chunk_size]
                    page_for_slice = para_page
                    prev_chunk_page = page_for_slice
                    chunks.append(
                        _emit_chunk(slice_text, page_for_slice, len(chunks))
                    )
                    if start + chunk_size >= len(para_text):
                        # Last slice — seed the overlap prefix for the next window.
                        overlap_prefix = slice_text[-overlap:] if overlap > 0 else ""
                        window_text = ""
                        window_page = None
                        break
                    start += chunk_size - overlap
                paragraph_idx += 1

    # Emit any remaining window.
    if window_text:
        chunks.append(_emit_chunk(window_text, window_page, len(chunks)))

    return chunks
