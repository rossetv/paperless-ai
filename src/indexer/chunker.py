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

# Hard character cap applied after chunking so no chunk exceeds the embedding
# model's 8191-token limit. CHUNK_SIZE is in characters, but dense CJK or
# base64-like OCR can pack far more tokens into them, and one oversized chunk
# fails the whole embedding batch with a non-retryable 400. 6000 stays under the
# limit even at ~1 token per character and leaves normal chunks untouched. A
# character cap avoids taking a dependency on tiktoken for exact counts.
_MAX_CHUNK_CHARS = 6000


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


def _assemble_chunks(
    paragraphs: list[tuple[int | None, str]],
    *,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    """Assemble ``(page_hint, text)`` paragraphs into overlapping TextChunks.

    Paragraphs accumulate into a window; when the next one would overflow
    ``chunk_size`` the window is emitted and a new one starts from the last
    ``overlap`` characters. Paragraphs larger than ``chunk_size`` are sliced
    directly.
    """
    chunks: list[TextChunk] = []
    overlap_prefix: str = ""
    window_page: int | None = None
    window_text: str = ""
    # True once a real paragraph is in the window, as opposed to only the
    # carried-over overlap prefix.
    window_has_para: bool = False
    prev_chunk_page: int | None = None

    def _emit(text: str, page: int | None) -> TextChunk:
        return TextChunk(chunk_index=len(chunks), text=text, page_hint=page)

    paragraph_idx = 0
    while paragraph_idx < len(paragraphs):
        para_page, para_text = paragraphs[paragraph_idx]

        if window_text == "" and overlap_prefix:
            window_text = overlap_prefix
            window_page = prev_chunk_page

        separator = "\n\n" if window_text else ""
        candidate = window_text + separator + para_text

        if len(candidate) <= chunk_size:
            window_text = candidate
            window_has_para = True
            if window_page is None and para_page is not None:
                window_page = para_page
            paragraph_idx += 1
        elif window_has_para:
            # Emit the window and retry this paragraph after the overlap tail.
            prev_chunk_page = window_page
            chunks.append(_emit(window_text, window_page))
            overlap_prefix = window_text[-overlap:] if overlap > 0 else ""
            window_text = ""
            window_page = None
            window_has_para = False
        elif window_text:
            # Only the overlap prefix is in the window and the paragraph does
            # not fit beside it. Drop the overlap: re-emitting the prefix and
            # retrying would loop forever, as it never shrinks. The paragraph is
            # retried in the now-empty window.
            overlap_prefix = ""
            window_text = ""
            window_page = None
        else:
            # The paragraph alone exceeds chunk_size: slice it directly.
            start = 0
            while start < len(para_text):
                slice_text = para_text[start : start + chunk_size]
                prev_chunk_page = para_page
                chunks.append(_emit(slice_text, para_page))
                if start + chunk_size >= len(para_text):
                    overlap_prefix = slice_text[-overlap:] if overlap > 0 else ""
                    window_text = ""
                    window_page = None
                    break
                start += chunk_size - overlap
            paragraph_idx += 1

    if window_text:
        chunks.append(_emit(window_text, window_page))

    return chunks


def _cap_chunk_sizes(chunks: list[TextChunk], *, max_chars: int) -> list[TextChunk]:
    """Hard-split any chunk longer than *max_chars*, re-numbering chunk_index.

    Sub-chunks inherit the parent's ``page_hint`` and get no overlap, which
    would reintroduce the size risk this guard removes.
    """
    if all(len(chunk.text) <= max_chars for chunk in chunks):
        return chunks

    capped: list[TextChunk] = []
    for chunk in chunks:
        if len(chunk.text) <= max_chars:
            capped.append(
                TextChunk(
                    chunk_index=len(capped),
                    text=chunk.text,
                    page_hint=chunk.page_hint,
                )
            )
            continue
        for start in range(0, len(chunk.text), max_chars):
            capped.append(
                TextChunk(
                    chunk_index=len(capped),
                    text=chunk.text[start : start + max_chars],
                    page_hint=chunk.page_hint,
                )
            )
    return capped


def chunk_text(
    content: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    """Split *content* into overlapping TextChunks, indexed contiguously from 0.

    Lines are grouped into paragraphs (blank lines separate them, page markers
    set the page hint), paragraphs are packed into ``chunk_size`` windows, then
    the hard character cap is applied. Blank *content* returns ``[]``.
    """
    if not 0 <= overlap < chunk_size:
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < chunk_size, got overlap={overlap!r} "
            f"chunk_size={chunk_size!r}"
        )

    if not content.strip():
        return []

    # Pass 1: parse lines into (page_number | None, paragraph_text) pairs.
    paragraphs: list[tuple[int | None, str]] = []
    current_page: int | None = None
    paragraph_lines: list[str] = []
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
            _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)
            paragraph_lines = []
            current_page = int(marker_match.group(1))
            paragraph_page = current_page
            continue

        if raw_line.strip() == "":
            _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)
            paragraph_lines = []
            paragraph_page = current_page
        else:
            if not paragraph_lines:
                paragraph_page = current_page
            paragraph_lines.append(raw_line)

    _flush_paragraph(paragraph_lines, paragraph_page, paragraphs)

    if not paragraphs:
        return []

    chunks = _assemble_chunks(paragraphs, chunk_size=chunk_size, overlap=overlap)
    return _cap_chunk_sizes(chunks, max_chars=_MAX_CHUNK_CHARS)
