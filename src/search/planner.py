"""LLM query planner — Stage 1 of the search pipeline.

The planner makes one LLM call using the configured SEARCH_PLANNER_MODEL
(falling back through CLASSIFY_MODELS on failure) and parses the JSON response
into a :class:`~search.models.RetrievalPlan` — a list of
:class:`~search.models.PlannedSpec` objects.

Design notes:
- No Pydantic; parsing follows the manual pattern from classifier/result.py
  (CODE_GUIDELINES.md §5.6).
- On any bad LLM response (malformed, empty, unparseable) the planner degrades
  gracefully: it returns a ``RetrievalPlan`` whose sole spec is a broad semantic
  search on the raw user query.  A WARNING is logged.  The pipeline never raises
  on a bad LLM response.
- All LLM calls go through ``OpenAIChatMixin._create_completion``
  (CODE_GUIDELINES.md §8.1): the planner subclasses the mixin and inherits the
  shared OpenAI singleton, the ``@retry`` exponential backoff, and the
  ``llm_limiter`` global concurrency limiter.  It iterates SEARCH_PLANNER_MODEL
  then CLASSIFY_MODELS, mirroring ``classifier/provider.ClassificationProvider``.
- A failing model — whether a retry-exhausted retryable error or a
  non-retryable one (``AuthenticationError``, ``PermissionDeniedError``,
  ``NotFoundError``, ``BadRequestError``) — is caught as ``openai.APIError``
  and the next model is tried.  When every model fails the planner degrades to
  the safe fallback plan.  ``plan()`` therefore never raises.
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
    PlannedSpec,
    RetrievalPlan,
)
from search.prompts import (
    PLANNER_SYSTEM_PROMPT,
    _planner_response_format,
    build_planner_user_message,
    build_replan_user_message,
)
from search.text import QUERY_LOG_PREFIX_CHARS

if TYPE_CHECKING:
    from common.config import Settings
    from common.llm import LlmCallUsage
    from search.models import RetrievalSpec

log = structlog.get_logger(__name__)

# The "search-query planning engine" opening phrase in PLANNER_SYSTEM_PROMPT is
# the routing key the scripted test client keys off via ScriptedLLMClient.route.
# Keep it as the opening words of the prompt.  This constant documents that
# dependency so future prompt edits do not break the router silently.
_PLANNER_ROUTING_PHRASE = "search-query planning engine"


class QueryPlanner(OpenAIChatMixin):
    """Converts a raw user query into a structured RetrievalPlan via one LLM call.

    The planner is a pure function wrapped in a class for dependency injection.
    All state is in the injected ``settings``; QueryPlanner instances are safe
    to share across threads.

    LLM calls go through the inherited ``OpenAIChatMixin._create_completion``,
    which owns the shared OpenAI client singleton, retry, and the concurrency
    limiter (CODE_GUIDELINES.md §8.1).

    Args:
        settings: Application settings; supplies SEARCH_PLANNER_MODEL and
            CLASSIFY_MODELS for the fallback chain, plus MAX_RETRIES /
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
        *,
        taxonomy_block: str = "",
    ) -> RetrievalPlan | ClarifyNeeded:
        """Analyse *query* and return a RetrievalPlan or ClarifyNeeded.

        Makes one LLM call using SEARCH_PLANNER_MODEL, falling back through
        CLASSIFY_MODELS on any API error.  The response is **either** a normal
        plan (a list of PlannedSpecs) **or** a clarify signal (when
        ``SEARCH_GATE_ADEQUACY`` is True and the model judges the query
        obviously inadequate).

        **Fail-open guarantee:** any parse failure, empty/malformed response, or
        ``SEARCH_GATE_ADEQUACY=False`` → returns a RetrievalPlan (the safe
        fallback, containing a single broad semantic spec).  A degraded LLM
        response NEVER becomes a false clarify.

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
            A frozen RetrievalPlan or ClarifyNeeded.  Never raises.
        """
        today = date.today().isoformat()
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_planner_user_message(
                    query=query, today=today, asker=asker, taxonomy_block=taxonomy_block
                ),
            },
        ]

        return self._complete_and_parse(query, messages, usage_sink)

    def replan(
        self,
        query: str,
        *,
        hint: str,
        prior_specs: tuple[RetrievalSpec, ...],
        prior_findings: tuple[str, ...],
        asker: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
        taxonomy_block: str = "",
    ) -> RetrievalPlan | ClarifyNeeded:
        """Re-plan to target the synthesiser's gap hint (Phase 2 refinement).

        Reuses the byte-stable :data:`PLANNER_SYSTEM_PROMPT` and the exact same
        schema / parse path as :meth:`plan`, but builds a richer user turn via
        :func:`~search.prompts.build_replan_user_message` that gives the model
        the gap to close, the specs already tried, and the documents already
        found, then asks for DIFFERENT specs that target the gap.

        **Fail-open guarantee:** identical to :meth:`plan` — any parse failure,
        empty / malformed response, or every model failing degrades to the safe
        broad-semantic fallback plan.  Never raises.

        Args:
            query: The raw user search query.
            hint: The synthesiser's adjustment hint — the gap to close.
            prior_specs: The resolved specs already tried in the first pass,
                rendered into the user turn so the model avoids repeating them.
            prior_findings: Titles of the documents already found (may be
                empty), rendered so the model knows what is already covered.
            asker: The sanitised asker identity, or None for an anonymous query.
            usage_sink: Optional list to receive the re-plan call's token usage.

        Returns:
            A frozen RetrievalPlan or ClarifyNeeded.  Never raises.
        """
        today = date.today().isoformat()
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_replan_user_message(
                    query=query,
                    today=today,
                    hint=hint,
                    prior_specs=prior_specs,
                    prior_findings=prior_findings,
                    asker=asker,
                    taxonomy_block=taxonomy_block,
                ),
            },
        ]
        return self._complete_and_parse(query, messages, usage_sink)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _complete_and_parse(
        self,
        query: str,
        messages: list[dict[str, str]],
        usage_sink: list[LlmCallUsage] | None,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the model-fallback completion and parse it, shared by plan/replan.

        Both :meth:`plan` and :meth:`replan` differ only in the user message;
        the model fallback chain, the response format, and the parse path are
        identical, so they live here once (CODE_GUIDELINES §1.3).  Returns the
        safe fallback plan when every model failed or returned empty content.
        """
        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_PLANNER_MODEL,
            messages=messages,
            fallback_models=self.settings.CLASSIFY_MODELS,
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

    def _parse_response(self, query: str, raw: str) -> RetrievalPlan | ClarifyNeeded:
        """Parse *raw* into a RetrievalPlan or ClarifyNeeded.

        Fail-open: any malformed, empty, or unparseable response falls back to a
        RetrievalPlan — a degraded LLM response must NEVER become a false clarify.
        The clarify branch is only taken when SEARCH_GATE_ADEQUACY is True and
        the response carries a non-empty ``clarify.reason``.

        Args:
            query: Original user query — used as the fallback semantic spec.
            raw: Raw text returned by the LLM.

        Returns:
            A RetrievalPlan (the normal or fallback case) or ClarifyNeeded (when
            the model signals the query is obviously inadequate and the gate is on).
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

        if "specs" not in data:
            return self._fallback_plan(
                query, reason="LLM response missing required key 'specs'"
            )

        try:
            return _build_retrieval_plan(data, self.settings.SEARCH_PLANNER_MAX_SPECS)
        except (KeyError, TypeError, ValueError) as exc:
            return self._fallback_plan(
                query, reason=f"LLM response had unexpected structure: {exc}"
            )

    def _fallback_plan(self, query: str, reason: str) -> RetrievalPlan:
        """Return the minimal safe fallback plan and log a warning.

        The fallback plan contains a single broad semantic spec on the raw query
        with empty filters.  The pipeline can always proceed with at least a
        single vector search on the original query text.

        Args:
            query: The raw user query.
            reason: Human-readable explanation for the fallback, for log triage.

        Returns:
            A RetrievalPlan with one broad semantic spec.
        """
        log.warning(
            "planner.degraded_to_fallback",
            reason=reason,
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
        )
        return RetrievalPlan(
            specs=(
                PlannedSpec(
                    mode="semantic",
                    semantic=query,
                    keywords=(),
                    filter_guess=EMPTY_FILTER_CANDIDATES,
                    rationale="fallback: broad semantic search",
                ),
            ),
            clarify=None,
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


def _build_retrieval_plan(data: dict[str, object], max_specs: int) -> RetrievalPlan:
    """Construct a RetrievalPlan from a validated dict.

    Reads ``data["specs"]`` (a list), builds :class:`~search.models.PlannedSpec`
    objects (coercing via :func:`_str_list` / :func:`_str_or_none`), caps the
    list at *max_specs*, and returns a :class:`~search.models.RetrievalPlan`.

    Args:
        data: A dict parsed from the LLM JSON response.  Must contain ``specs``.
        max_specs: Maximum number of specs to keep (``SEARCH_PLANNER_MAX_SPECS``).

    Returns:
        A frozen RetrievalPlan dataclass.

    Raises:
        KeyError: If a required nested key is absent.
        TypeError: If a field has an unexpected type.
    """
    raw_specs = data.get("specs")
    if not isinstance(raw_specs, list):
        raw_specs = []

    planned_specs: list[PlannedSpec] = []
    for item in raw_specs:
        if not isinstance(item, dict):
            continue

        # mode must be "semantic" or "keyword"; default malformed values to "semantic".
        mode_raw = item.get("mode")
        mode: str
        if mode_raw in ("semantic", "keyword"):
            mode = mode_raw
        else:
            mode = "semantic"

        semantic = _str_or_none(item.get("semantic"))
        keywords = tuple(t for t in _str_list(item.get("keywords")) if t)
        rationale = _str_or_none(item.get("rationale")) or ""

        raw_fg = item.get("filter_guess")
        fg_raw: dict[str, object] = raw_fg if isinstance(raw_fg, dict) else {}
        filter_guess = FilterCandidates(
            correspondent=_str_or_none(fg_raw.get("correspondent")),
            document_type=_str_or_none(fg_raw.get("document_type")),
            tags=tuple(t for t in _str_list(fg_raw.get("tags")) if t),
            date_from=_str_or_none(fg_raw.get("date_from")),
            date_to=_str_or_none(fg_raw.get("date_to")),
        )

        planned_specs.append(
            PlannedSpec(
                mode=mode,  # type: ignore[arg-type]
                semantic=semantic,
                keywords=keywords,
                filter_guess=filter_guess,
                rationale=rationale,
            )
        )

    # Cap at SEARCH_PLANNER_MAX_SPECS — a model returning more than asked must
    # not multiply retrieval passes on a billable, network-facing endpoint.
    capped = tuple(planned_specs[:max_specs])

    return RetrievalPlan(specs=capped, clarify=None)


def _str_list(value: object) -> list[str]:
    """Coerce an LLM-supplied list-shaped field into a list of strings.

    LLMs frequently emit a bare string where the schema asks for a list —
    e.g. ``"keywords": "invoice"`` instead of ``["invoice"]``.  Iterating
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
