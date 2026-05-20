"""Combines per-page OCR results into a single document text."""

from __future__ import annotations

from dataclasses import dataclass

# Inserted into the document content when OCR fails for a page, so downstream
# steps (and humans) can see where the pipeline broke.
OCR_ERROR_MARKER = "[OCR ERROR]"


# frozen+slots dataclass: the result of transcribing one page — its text and
# the model that produced it.  Replacing the bare ``(text, model)`` tuple
# (CODE_GUIDELINES §5.2/§5.8) means the provider, the worker, and this module
# stop indexing ``[0]``/``[1]`` and read named attributes instead.
@dataclass(frozen=True, slots=True)
class PageResult:
    """One transcribed page: its text and the model that produced it.

    Attributes:
        text: The transcribed page text; the empty string for a blank page.
        model: The model identifier that produced *text*; the empty string
            when no model contributed (a blank page or a failed transcription).
    """

    text: str
    model: str


def assemble_full_text(
    page_count: int,
    page_results: list[PageResult],
    *,
    include_page_models: bool = False,
) -> tuple[str, set[str]]:
    """Combine per-page OCR results into a single document text.

    Multi-page documents get ``--- Page N ---`` headers between sections.
    A footer listing all models used is appended at the end.

    Args:
        page_count: Total number of pages in the document (used to decide
            whether to emit page headers).
        page_results: Ordered list of :class:`PageResult` values, one per
            page.  Entries with empty *text* are skipped.
        include_page_models: If ``True``, append the model name to each page
            header (e.g. ``--- Page 1 (gpt-5.4-mini) ---``).

    Returns:
        A ``(full_text, models_used)`` tuple where *full_text* is the
        assembled document text and *models_used* is the set of distinct
        model identifiers that contributed.
    """
    sections: list[str] = []
    models_used: set[str] = set()

    for index, page in enumerate(page_results, 1):
        if not page.text.strip():
            continue
        header = ""
        if page_count > 1:
            header = f"--- Page {index}"
            if include_page_models and page.model:
                header += f" ({page.model})"
            header += " ---\n"
        sections.append(f"{header}{page.text}")
        if page.model:
            models_used.add(page.model)

    full_text = "\n\n".join(sections)
    if models_used:
        footer = f"Transcribed by model: {', '.join(sorted(models_used))}"
        full_text = f"{full_text}\n\n{footer}" if full_text else footer

    return full_text, models_used
