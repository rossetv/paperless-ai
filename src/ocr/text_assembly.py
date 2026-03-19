"""Combines per-page OCR results into a single document text."""

from __future__ import annotations

# Inserted into the document content when OCR fails for a page, so downstream
# steps (and humans) can see where the pipeline broke.
OCR_ERROR_MARKER = "[OCR ERROR]"


def assemble_full_text(
    page_count: int,
    page_results: list[tuple[str, str]],
    *,
    include_page_models: bool = False,
) -> tuple[str, set[str]]:
    """Combine per-page OCR results into a single document text.

    Multi-page documents get ``--- Page N ---`` headers between sections.
    A footer listing all models used is appended at the end.

    Args:
        page_count: Total number of pages in the document (used to decide
            whether to emit page headers).
        page_results: Ordered list of ``(text, model_name)`` tuples, one per
            page.  Empty *text* entries are skipped.
        include_page_models: If ``True``, append the model name to each page
            header (e.g. ``--- Page 1 (gpt-5-mini) ---``).

    Returns:
        A ``(full_text, models_used)`` tuple where *full_text* is the
        assembled document text and *models_used* is the set of distinct
        model identifiers that contributed.
    """
    sections: list[str] = []
    models_used: set[str] = set()

    for i, (text, model) in enumerate(page_results, 1):
        if not text.strip():
            continue
        header = ""
        if page_count > 1:
            header = f"--- Page {i}"
            if include_page_models and model:
                header += f" ({model})"
            header += " ---\n"
        sections.append(f"{header}{text}")
        if model:
            models_used.add(model)

    full_text = "\n\n".join(sections)
    if models_used:
        footer = f"Transcribed by model: {', '.join(sorted(models_used))}"
        full_text = f"{full_text}\n\n{footer}" if full_text else footer

    return full_text, models_used
