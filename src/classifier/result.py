"""Classification result dataclass and JSON response parser."""

from __future__ import annotations

import json
from dataclasses import dataclass


# frozen dataclass: this is a structured value object constructed after parsing
# LLM JSON output.  frozen=True enforces immutability so results can be safely
# shared across threads and logged without risk of accidental mutation.
@dataclass(frozen=True)
class ClassificationResult:
    """Immutable container for classification LLM output fields."""

    title: str
    correspondent: str
    tags: list[str]
    document_date: str
    document_type: str
    language: str
    person: str


def _extract_json(text: str) -> dict:
    """
    Parse JSON from raw model output, trimming markdown fences if present.

    Some models wrap their response in ````` ``` ````` code blocks or add
    preamble text.  This function tries a strict parse first, then falls
    back to extracting the first ``{…}`` substring.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def parse_classification_response(text: str) -> ClassificationResult:
    """
    Parse and sanitize a classification JSON response into a typed result.

    Handles common LLM quirks:
    - ``tags`` may arrive as a string instead of a list.
    - Fields may be ``null`` instead of empty strings.
    - The JSON may be wrapped in markdown fences.

    Raises:
        ValueError: When the response is empty or not a JSON object.
        json.JSONDecodeError: When the JSON cannot be parsed.
    """
    raw = text.strip()
    if not raw:
        raise ValueError("Classification response is empty.")

    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Classification response is not a JSON object.")

    def get_str(key: str) -> str:
        value = data.get(key, "")
        return str(value).strip() if value is not None else ""

    # Coerce the tags field: the LLM sometimes returns a single string
    tags_value = data.get("tags", [])
    if isinstance(tags_value, str):
        tags_list = [tags_value] if tags_value.strip() else []
    elif isinstance(tags_value, list):
        tags_list = tags_value
    else:
        tags_list = []

    tags = [str(tag).strip() for tag in tags_list if str(tag).strip()]

    return ClassificationResult(
        title=get_str("title"),
        correspondent=get_str("correspondent"),
        tags=tags,
        document_date=get_str("document_date"),
        document_type=get_str("document_type"),
        language=get_str("language"),
        person=get_str("person"),
    )
