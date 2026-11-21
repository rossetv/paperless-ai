"""Combines per-page OCR results into a single document text."""

from __future__ import annotations

from dataclasses import dataclass

# Stands in for a page whose OCR failed, so readers can see where it broke.
OCR_ERROR_MARKER = "[OCR ERROR]"


@dataclass(frozen=True, slots=True)
class PageResult:
    """One transcribed page: its text and the model that produced it.

    Both are empty for a blank page; *model* is empty for a failed one.
    """

    text: str
    model: str


def assemble_full_text(
    page_count: int,
    page_results: list[PageResult],
    *,
    include_page_models: bool = False,
) -> tuple[str, set[str]]:
    """Combine per-page OCR results into one text; return it and the models used.

    Multi-page documents get ``--- Page N ---`` headers (with the model name
    when *include_page_models*), blank pages are skipped, and a footer lists
    the models.
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
