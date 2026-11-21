"""Classification result dataclass and JSON response parser."""

from __future__ import annotations

from dataclasses import dataclass

from common.llm import extract_json_object


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Immutable container for classification LLM output fields."""

    title: str
    correspondent: str
    # A tuple, so the frozen dataclass cannot be mutated through tags.append().
    tags: tuple[str, ...]
    document_date: str
    document_type: str
    language: str
    person: str


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

    data = extract_json_object(raw)
    if not isinstance(data, dict):
        raise ValueError("Classification response is not a JSON object.")

    def get_str(key: str) -> str:
        value = data.get(key, "")
        if value is None:
            return ""
        # Without JSON-schema enforcement (Ollama, fallback models) the LLM can
        # return ``false`` or ``0`` for text fields; writing "False" into
        # Paperless would be nonsense, so non-string scalars count as absent.
        if isinstance(value, (bool, int, float)):
            return ""
        return str(value).strip()

    # The LLM sometimes returns a single string instead of a list.
    tags_value = data.get("tags", [])
    if isinstance(tags_value, str):
        tags_list = [tags_value] if tags_value.strip() else []
    elif isinstance(tags_value, list):
        tags_list = tags_value
    else:
        tags_list = []

    tags = tuple(str(tag).strip() for tag in tags_list if str(tag).strip())

    return ClassificationResult(
        title=get_str("title"),
        correspondent=get_str("correspondent"),
        tags=tags,
        document_date=get_str("document_date"),
        document_type=get_str("document_type"),
        language=get_str("language"),
        person=get_str("person"),
    )
