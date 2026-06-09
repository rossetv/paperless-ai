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
from search.models import (
    EMPTY_FILTER_CANDIDATES,
    ClarifyNeeded,
    FilterCandidates,
    QueryPlan,
)
from search.prompts import (
    PLANNER_SYSTEM_PROMPT,
    _planner_response_format,
    build_planner_user_message,
)
from search.text import QUERY_LOG_PREFIX_CHARS

if TYPE_CHECKING:
    from common.config import Settings
    from common.llm import LlmCallUsage

log = structlog.get_logger(__name__)

# The documented plan width (the planner prompt asks for these maxima). They are
# enforced in code, not merely requested, so the per-query vector_search fan-out
# is bounded regardless of model output: each semantic query and each
# sub-question becomes one KNN pass holding the store reader lock, and this
# endpoint is billable and network-facing (SRCH-03, CODE_GUIDELINES §14.6). The
# JSON schema cannot bound array length, so the bound lives here.
_MAX_SEMANTIC_QUERIES = 3
_MAX_SUB_QUESTIONS = 3


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
        # via duck-typing — it must not be renamed.
        self.settings = settings
        self._init_stats()

    def plan(
        self,
        query: str,
        asker: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
    ) -> QueryPlan | ClarifyNeeded:
        """Analyse *query* and return a QueryPlan or ClarifyNeeded.

        Makes one LLM call using SEARCH_PLANNER_MODEL, falling back through
        AI_MODELS on any API error.  The response is **either** a normal plan
        **or** a clarify signal (when ``SEARCH_GATE_ADEQUACY`` is True and the
        model judges the query obviously inadequate).

        **Fail-open guarantee:** any parse failure, empty/malformed response, or
        ``SEARCH_GATE_ADEQUACY=False`` → returns a QueryPlan (the existing safe
        fallback).  A degraded LLM response NEVER becomes a false clarify.

        Args:
            query: The raw user search query.
            asker: The sanitised asker identity (from
                :func:`~search.identity.resolve_asker`), or None for an
                anonymous query. When set, the planner user message includes an
                identity line so first-person references resolve to the asker.
            usage_sink: Optional list to receive one
                :class:`~common.llm.LlmCallUsage` record capturing the token
                usage for the planner call (the search telemetry). ``None``
                (the default) skips capture and keeps behaviour unchanged.

        Returns:
            A frozen QueryPlan or ClarifyNeeded.  Never raises.
        """
        today = date.today().isoformat()
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_planner_user_message(
                    query=query, today=today, asker=asker
                ),
            },
        ]

        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_PLANNER_MODEL,
            messages=messages,
            fallback_models=self.settings.AI_MODELS,
            log_event_prefix="planner",
            reasoning_effort=self.settings.SEARCH_PLANNER_REASONING_EFFORT,
            response_format=_planner_response_format(self.settings),
            usage_sink=usage_sink,
        )
        if raw_content is None:
            return self._fallback_plan(
                query, reason="all models failed or returned empty content"
            )

        return self._parse_response(query, raw_content)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_response(self, query: str, raw: str) -> QueryPlan | ClarifyNeeded:
        """Parse *raw* into a QueryPlan or ClarifyNeeded.

        Fail-open: any malformed, empty, or unparseable response falls back to a
        QueryPlan — a degraded LLM response must NEVER become a false clarify.
        The clarify branch is only taken when SEARCH_GATE_ADEQUACY is True and
        the response carries a non-empty ``clarify.reason``.

        Args:
            query: Original user query — used as the fallback semantic query.
            raw: Raw text returned by the LLM.

        Returns:
            A QueryPlan (the normal or fallback case) or ClarifyNeeded (when the
            model signals the query is obviously inadequate and the gate is on).
        """
        stripped = raw.strip()
        if not stripped:
            return self._fallback_plan(query, reason="LLM returned empty content")

        try:
            data = extract_json_object(stripped)
        except json.JSONDecodeError:
            return self._fallback_plan(query, reason="LLM response was not valid JSON")

        if not isinstance(data, dict):
            return self._fallback_plan(
                query, reason="LLM response was not a JSON object"
            )

        # Adequacy gate (Layer 1): check for a clarify signal BEFORE the plan path.
        # Fail-open: only return ClarifyNeeded when the gate is on AND the model
        # provided a non-empty reason.  Any other shape falls through to the plan.
        if self.settings.SEARCH_GATE_ADEQUACY:
            clarify_outcome = _extract_clarify(data)
            if clarify_outcome is not None:
                log.info(
                    "planner.clarify_needed",
                    query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                    reason=clarify_outcome.reason,
                )
                return clarify_outcome

        if "semantic_queries" not in data:
            return self._fallback_plan(
                query, reason="LLM response missing required key 'semantic_queries'"
            )

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


def _extract_clarify(data: dict[str, object]) -> ClarifyNeeded | None:
    """Extract a ClarifyNeeded from *data* if it carries a valid clarify signal.

    Returns ``None`` (fall through to the plan path) when:
    - ``clarify`` is absent or null.
    - ``clarify`` is present but not a dict.
    - ``clarify.reason`` is absent, not a string, or empty / whitespace-only.

    This is the fail-open guard: an ambiguous or malformed clarify shape must
    never silently become a false rejection of a valid query.

    Args:
        data: A dict parsed from the LLM JSON response.

    Returns:
        A ClarifyNeeded if the signal is well-formed and non-empty, else None.
    """
    raw_clarify = data.get("clarify")
    if not isinstance(raw_clarify, dict):
        # Null, absent, or wrong type → not a clarify response.
        return None
    reason = raw_clarify.get("reason")
    if not isinstance(reason, str):
        return None
    reason_stripped = reason.strip()
    if not reason_stripped:
        return None
    return ClarifyNeeded(reason=reason_stripped)


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
    # Cap the two lists that drive vector_search fan-out at their documented
    # widths (SRCH-03): a model returning more than asked must not multiply the
    # KNN passes (and the store-lock holds) on a billable endpoint.
    semantic_queries = tuple(t for t in _str_list(data.get("semantic_queries")) if t)[
        :_MAX_SEMANTIC_QUERIES
    ]
    keyword_terms = tuple(t for t in _str_list(data.get("keyword_terms")) if t)
    sub_questions = tuple(t for t in _str_list(data.get("sub_questions")) if t)[
        :_MAX_SUB_QUESTIONS
    ]

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
