"""LLM query planner — Stage 1 of the search pipeline.

The planner makes one LLM call using the configured SEARCH_PLANNER_MODEL
(falling back through AI_MODELS on failure) and parses the JSON response
into a frozen QueryPlan dataclass.

Design notes:
- No Pydantic; parsing follows the manual pattern from classifier/result.py
  (CODE_GUIDELINES.md §5.6).
- On any bad LLM response (malformed, empty, unparseable) the planner
  degrades gracefully: it returns a minimal safe QueryPlan whose sole
  semantic query is the raw user query, with empty keyword_terms,
  sub_questions, and FilterCandidates.  A WARNING is logged.  The pipeline
  never raises on a bad LLM response.
- The llm_client is the OpenAI-compatible client injected by the caller; the
  planner calls llm_client.chat.completions.create(...) directly, iterating
  through AI_MODELS on OpenAI API errors (mirroring the classifier's
  model-fallback pattern).
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import openai
import structlog

from common.llm import unique_models
from search.models import FilterCandidates, QueryPlan
from search.prompts import build_planner_system_prompt

if TYPE_CHECKING:
    from common.config import Settings

log = structlog.get_logger(__name__)

# OpenAI API errors that warrant trying the next model in the fallback chain.
_RETRYABLE_ERRORS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class QueryPlanner:
    """Converts a raw user query into a structured QueryPlan via one LLM call.

    The planner is a pure function wrapped in a class for dependency injection.
    All state is in the injected ``settings`` and ``llm_client``; QueryPlanner
    instances are safe to share across threads.

    Args:
        settings: Application settings; supplies SEARCH_PLANNER_MODEL and
            AI_MODELS for the fallback chain.
        llm_client: An OpenAI-compatible client (``openai.OpenAI`` or a mock
            in tests).  Must expose ``chat.completions.create``.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        self._settings = settings
        self._llm_client = llm_client

    def plan(self, query: str) -> QueryPlan:
        """Analyse *query* and return a QueryPlan for the retrieval stages.

        Makes one LLM call using SEARCH_PLANNER_MODEL, falling back through
        AI_MODELS on retryable API errors.  On any parse failure or exhausted
        fallback, returns a minimal safe plan containing only the raw query.

        Args:
            query: The raw user search query.

        Returns:
            A frozen QueryPlan.  Never raises.
        """
        today = date.today().isoformat()
        system_prompt = build_planner_system_prompt(today=today)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        raw_content = self._call_llm_with_fallback(query, messages)
        if raw_content is None:
            return self._fallback_plan(query, reason="all models failed or returned empty content")

        return self._parse_response(query, raw_content)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm_with_fallback(
        self, query: str, messages: list[dict[str, str]]
    ) -> str | None:
        """Try SEARCH_PLANNER_MODEL first, then each model in AI_MODELS.

        Returns the raw text content from the first successful call, or
        None if every model fails.

        The primary model (SEARCH_PLANNER_MODEL) is tried first.  If it is
        already in AI_MODELS it is not tried twice — unique_models deduplicates
        the combined list while preserving insertion order.
        """
        primary = self._settings.SEARCH_PLANNER_MODEL
        fallbacks = unique_models([primary] + list(self._settings.AI_MODELS))

        for model in fallbacks:
            try:
                completion = self._llm_client.chat.completions.create(  # type: ignore[attr-defined]
                    model=model,
                    messages=messages,
                )
                content: str = completion.choices[0].message.content or ""
                return content
            except _RETRYABLE_ERRORS as exc:
                log.warning(
                    "planner.model_failed",
                    model=model,
                    error=str(exc),
                    query_prefix=query[:60],
                )
                continue
            except openai.BadRequestError as exc:
                # A 400 is not recoverable by retrying the same query; skip
                # this model rather than crashing the plan.
                log.warning(
                    "planner.model_rejected_request",
                    model=model,
                    error=str(exc),
                    query_prefix=query[:60],
                )
                continue

        return None

    def _parse_response(self, query: str, raw: str) -> QueryPlan:
        """Parse *raw* into a QueryPlan, falling back gracefully on any error.

        Args:
            query: Original user query — used as the fallback semantic query.
            raw: Raw text returned by the LLM.

        Returns:
            A fully-populated QueryPlan, or the safe fallback plan.
        """
        stripped = raw.strip()
        if not stripped:
            return self._fallback_plan(query, reason="LLM returned empty content")

        try:
            data = _extract_json(stripped)
        except (json.JSONDecodeError, ValueError):
            return self._fallback_plan(query, reason="LLM response was not valid JSON")

        if not isinstance(data, dict):
            return self._fallback_plan(query, reason="LLM response was not a JSON object")

        if "semantic_queries" not in data:
            return self._fallback_plan(query, reason="LLM response missing required key 'semantic_queries'")

        try:
            return _build_query_plan(data)
        except (KeyError, TypeError, ValueError) as exc:
            return self._fallback_plan(
                query, reason=f"LLM response had unexpected structure: {exc}"
            )

    def _fallback_plan(self, query: str, reason: str) -> QueryPlan:
        """Return the minimal safe fallback plan and log a warning.

        The fallback plan contains the raw query as the sole semantic query and
        empty values for every other field.  The pipeline can always proceed
        with at least a single vector search on the original query text.

        Args:
            query: The raw user query.
            reason: Human-readable explanation for the fallback, for log triage.

        Returns:
            A minimal safe QueryPlan.
        """
        log.warning(
            "planner.degraded_to_fallback",
            reason=reason,
            query_prefix=query[:60],
        )
        return QueryPlan(
            semantic_queries=(query,),
            keyword_terms=(),
            filter_candidates=FilterCandidates(
                correspondent=None,
                document_type=None,
                tags=(),
                date_from=None,
                date_to=None,
            ),
            sub_questions=(),
        )


# ---------------------------------------------------------------------------
# Module-level parsing helpers (no side effects, no class state)
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> object:
    """Extract and parse JSON from raw model output.

    Tolerates markdown fences (``` or ```json ... ```) and preamble text.
    Tries a strict parse first, then falls back to extracting the first
    {…} substring — mirroring the classifier/result.py pattern.

    Args:
        text: Raw model output string.

    Returns:
        The parsed Python object.

    Raises:
        json.JSONDecodeError: When no valid JSON can be found.
        ValueError: When the extracted substring is empty.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _build_query_plan(data: dict) -> QueryPlan:  # type: ignore[type-arg]
    """Construct a QueryPlan from a validated dict.

    Args:
        data: A dict parsed from the LLM JSON response.  Must contain
            ``semantic_queries``; all other keys are optional and default
            to empty.

    Returns:
        A frozen QueryPlan dataclass.

    Raises:
        KeyError: If a required nested key is absent.
        TypeError: If a field has an unexpected type.
    """
    semantic_queries = tuple(
        str(q) for q in (data.get("semantic_queries") or []) if q
    )
    keyword_terms = tuple(
        str(t) for t in (data.get("keyword_terms") or []) if t
    )
    sub_questions = tuple(
        str(q) for q in (data.get("sub_questions") or []) if q
    )

    fc_raw = data.get("filter_candidates") or {}
    filter_candidates = FilterCandidates(
        correspondent=_str_or_none(fc_raw.get("correspondent")),
        document_type=_str_or_none(fc_raw.get("document_type")),
        tags=tuple(str(t) for t in (fc_raw.get("tags") or []) if t),
        date_from=_str_or_none(fc_raw.get("date_from")),
        date_to=_str_or_none(fc_raw.get("date_to")),
    )

    return QueryPlan(
        semantic_queries=semantic_queries,
        keyword_terms=keyword_terms,
        filter_candidates=filter_candidates,
        sub_questions=sub_questions,
    )


def _str_or_none(value: object) -> str | None:
    """Return *value* as a stripped string, or None when falsy."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
