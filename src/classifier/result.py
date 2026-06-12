"""Classification result dataclass and JSON response parser."""

from __future__ import annotations

from dataclasses import dataclass

from common.llm import extract_json_object


# frozen dataclass: this is a structured value object constructed after parsing
# LLM JSON output.  frozen=True enforces immutability so results can be safely
# shared across threads and logged without risk of accidental mutation;
# slots=True shaves memory and prevents attribute typos (CODE_GUIDELINES §5.2).
@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Immutable container for classification LLM output fields."""

    title: str
    correspondent: str
    # tuple, not list: a frozen dataclass with a mutable list field is only
    # half-frozen — result.tags.append(...) would silently mutate "frozen"
    # state. A tuple makes the immutability contract real (CODE_GUIDELINES §5.2).
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
        # Treat None as absent → empty string, as before.
        if value is None:
            return ""
        # On providers without JSON-schema enforcement the LLM can return
        # scalars such as ``false`` or ``0`` for text fields.  Coercing those
        # to "False"/"0" would write nonsense taxonomy names into Paperless, so
        # we treat non-string scalar types as absent instead.  OpenAI with a
        # JSON schema always delivers strings here, so this guard does not
        # affect the happy path.
        if isinstance(value, (bool, int, float)):
            return ""
        return str(value).strip()

    # Coerce the tags field: the LLM sometimes returns a single string
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
