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
- All LLM calls go through ``OpenAIChatMixin._create_completion``
  (CODE_GUIDELINES.md §8.1): the planner subclasses the mixin and inherits
  the shared OpenAI singleton, the ``@retry`` exponential backoff, and the
  ``llm_limiter`` global concurrency limiter.  It iterates SEARCH_PLANNER_MODEL
  then AI_MODELS, mirroring ``classifier/provider.ClassificationProvider``.
- A failing model — whether a retry-exhausted retryable error or a
  non-retryable one (``AuthenticationError``, ``PermissionDeniedError``,
  ``NotFoundError``, ``BadRequestError``) — is caught as ``openai.APIError``
  and the next model is tried.  When every model fails the planner degrades
  to the safe fallback plan.  ``plan()`` therefore never raises.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import structlog

from common.llm import OpenAIChatMixin, extract_json_object
from search.models import EMPTY_FILTER_CANDIDATES, FilterCandidates, QueryPlan
from search.prompts import build_planner_system_prompt
from search.text import QUERY_LOG_PREFIX_CHARS

if TYPE_CHECKING:
    from common.config import Settings

log = structlog.get_logger(__name__)


class QueryPlanner(OpenAIChatMixin):
    """Converts a raw user query into a structured QueryPlan via one LLM call.

    The planner is a pure function wrapped in a class for dependency injection.
    All state is in the injected ``settings``; QueryPlanner instances are safe
    to share across threads.

    LLM calls go through the inherited ``OpenAIChatMixin._create_completion``,
    which owns the shared OpenAI client singleton, retry, and the concurrency
    limiter (CODE_GUIDELINES.md §8.1).

    Args:
        settings: Application settings; supplies SEARCH_PLANNER_MODEL and
            AI_MODELS for the fallback chain, plus MAX_RETRIES /
            MAX_RETRY_BACKOFF_SECONDS for the inherited retry decorator.
    """

    # The planner keeps no stats; an empty tuple satisfies the mixin contract.
    _STAT_KEYS: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` is the attribute name the @retry decorator reads
        # via the HasRetrySettings protocol — it must not be renamed.
        self.settings = settings
        self._init_stats()

    def plan(self, query: str) -> QueryPlan:
        """Analyse *query* and return a QueryPlan for the retrieval stages.

        Makes one LLM call using SEARCH_PLANNER_MODEL, falling back through
        AI_MODELS on any API error.  On any parse failure or exhausted
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

        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_PLANNER_MODEL,
            messages=messages,
            fallback_models=self.settings.AI_MODELS,
            log_event_prefix="planner",
        )
        if raw_content is None:
            return self._fallback_plan(query, reason="all models failed or returned empty content")

        return self._parse_response(query, raw_content)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
            data = extract_json_object(stripped)
        except json.JSONDecodeError:
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
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
        )
        return QueryPlan(
            semantic_queries=(query,),
            keyword_terms=(),
            filter_candidates=EMPTY_FILTER_CANDIDATES,
            sub_questions=(),
        )


# ---------------------------------------------------------------------------
# Module-level parsing helpers (no side effects, no class state)
# ---------------------------------------------------------------------------


def _build_query_plan(data: dict[str, object]) -> QueryPlan:
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
    semantic_queries = tuple(t for t in _str_list(data.get("semantic_queries")) if t)
    keyword_terms = tuple(t for t in _str_list(data.get("keyword_terms")) if t)
    sub_questions = tuple(t for t in _str_list(data.get("sub_questions")) if t)

    raw_filter_candidates = data.get("filter_candidates")
    fc_raw: dict[str, object] = (
        raw_filter_candidates if isinstance(raw_filter_candidates, dict) else {}
    )
    filter_candidates = FilterCandidates(
        correspondent=_str_or_none(fc_raw.get("correspondent")),
        document_type=_str_or_none(fc_raw.get("document_type")),
        tags=tuple(t for t in _str_list(fc_raw.get("tags")) if t),
        date_from=_str_or_none(fc_raw.get("date_from")),
        date_to=_str_or_none(fc_raw.get("date_to")),
    )

    return QueryPlan(
        semantic_queries=semantic_queries,
        keyword_terms=keyword_terms,
        filter_candidates=filter_candidates,
        sub_questions=sub_questions,
    )


def _str_list(value: object) -> list[str]:
    """Coerce an LLM-supplied list-shaped field into a list of strings.

    LLMs frequently emit a bare string where the schema asks for a list —
    e.g. ``"keyword_terms": "invoice"`` instead of ``["invoice"]``.  Iterating
    such a string character-by-character (``str(t) for t in value``) yields
    garbage (``['i', 'n', 'v', ...]``) that poisons retrieval.  This helper
    handles every shape:

    - ``None`` or any non-string scalar (int, dict, …) → ``[]`` (no terms).
    - a bare string → ``[value]`` (the single intended term).
    - a list → each item ``str()``-ed (empty-string items are kept here; the
      caller filters falsy entries).

    Args:
        value: The raw value pulled from the parsed LLM JSON.

    Returns:
        A list of strings safe to feed into retrieval.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _str_or_none(value: object) -> str | None:
    """Return *value* as a stripped string, or None.

    Only ``str``, ``int``, and ``float`` scalars are coerced.  Any other type
    — notably a ``list`` or ``dict`` — returns ``None`` rather than its
    ``repr``: an LLM that emits ``"correspondent": ["npower", "EDF"]`` must
    not produce the filter candidate ``"['npower', 'EDF']"``.

    Args:
        value: The raw value pulled from the parsed LLM JSON.

    Returns:
        The stripped string form, or ``None`` when empty or not a scalar.
    """
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text if text else None
