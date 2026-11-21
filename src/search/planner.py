"""LLM query planner: the first stage of the search pipeline.

One call to SEARCH_PLANNER_MODEL (falling back through CLASSIFY_MODELS) whose
JSON response is parsed into a :class:`~search.models.RetrievalPlan`. Every
failure (each model erroring, or a bad response) degrades to a broad semantic
search on the raw query, so ``plan()`` never raises.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import structlog

from common.llm import OpenAIChatMixin, extract_json_object
from search.models import (
    ClarifyNeeded,
    FilterCandidates,
    PlannedSpec,
    RetrievalPlan,
)
from search.refinement import build_broad_semantic_plan
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


class QueryPlanner(OpenAIChatMixin):
    """Converts a raw user query into a structured RetrievalPlan via one LLM call.

    Stateless beyond the injected ``settings``, so safe to share across threads.
    """

    _STAT_KEYS: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` is the attribute name the @retry decorator reads
        # via duck-typing — it must not be renamed.
        self.settings = settings
        self._init_stats()

    @property
    def _provider(self) -> str:
        """Route the planner's chat call to the planner step's provider."""
        return self.settings.SEARCH_PLANNER_PROVIDER

    def plan(
        self,
        query: str,
        asker: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
        *,
        taxonomy_block: str = "",
    ) -> RetrievalPlan | ClarifyNeeded:
        """Analyse *query* and return a RetrievalPlan or ClarifyNeeded. Never raises.

        ClarifyNeeded is returned only when ``SEARCH_GATE_ADEQUACY`` is on and the
        model judges the query obviously inadequate. Fail-open: a degraded
        response always becomes the broad fallback plan, never a false clarify.

        Args:
            asker: The sanitised asker identity, or None; when set, first-person
                references in the query resolve to it.
            usage_sink: Optional list that receives this call's token usage.
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
        """Re-plan to close the synthesiser's gap *hint*. Never raises.

        Same system prompt, schema and fail-open parse as :meth:`plan`; the user
        turn adds the hint, the specs already tried, and the titles already
        found (*prior_findings*), and asks for different specs.
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

    def _complete_and_parse(
        self,
        query: str,
        messages: list[dict[str, str]],
        usage_sink: list[LlmCallUsage] | None,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the model-fallback completion and parse it, shared by plan/replan."""
        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_PLANNER_MODEL,
            messages=messages,
            # Fall back to CLASSIFY_MODELS only when the planner and classifier
            # share a provider — otherwise those models belong to a different
            # endpoint and would 404 on this stage's client (per-step providers).
            fallback_models=(
                self.settings.CLASSIFY_MODELS
                if self.settings.SEARCH_PLANNER_PROVIDER
                == self.settings.CLASSIFY_PROVIDER
                else ()
            ),
            log_event_prefix="planner",
            # reasoning_effort is OpenAI-only; omit it for a non-OpenAI planner.
            reasoning_effort=(
                self.settings.SEARCH_PLANNER_REASONING_EFFORT
                if self.settings.SEARCH_PLANNER_PROVIDER == "openai"
                else None
            ),
            response_format=_planner_response_format(self.settings),
            # Explicit standard tier on OpenAI — never flex here (a human is
            # waiting), and an explicit tier dodges the live-verified 401 on
            # tierless requests. Omitted for non-OpenAI providers.
            service_tier=(
                "default" if self.settings.SEARCH_PLANNER_PROVIDER == "openai" else None
            ),
            usage_sink=usage_sink,
        )
        if raw_content is None:
            return self._fallback_plan(
                query, reason="all models failed or returned empty content"
            )
        return self._parse_response(query, raw_content)

    def _parse_response(self, query: str, raw: str) -> RetrievalPlan | ClarifyNeeded:
        """Parse *raw* into a RetrievalPlan or ClarifyNeeded, failing open to a plan.

        Clarify is taken only when SEARCH_GATE_ADEQUACY is on and the response
        carries a non-empty ``clarify.reason``.
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
            return _build_retrieval_plan(
                data, self.settings.SEARCH_PLANNER_MAX_SPECS, query=query
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._fallback_plan(
                query, reason=f"LLM response had unexpected structure: {exc}"
            )

    def _fallback_plan(self, query: str, reason: str) -> RetrievalPlan:
        """Log *reason* and return one broad semantic spec on the raw query."""
        log.warning(
            "planner.degraded_to_fallback",
            reason=reason,
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
        )
        return build_broad_semantic_plan(
            query, rationale="fallback: broad semantic search"
        )


def _extract_clarify(data: dict[str, object]) -> ClarifyNeeded | None:
    """Return a ClarifyNeeded only for a dict ``clarify`` with a non-blank reason.

    Any other shape returns ``None``, so a malformed signal never rejects a
    valid query.
    """
    raw_clarify = data.get("clarify")
    if not isinstance(raw_clarify, dict):
        return None
    reason = raw_clarify.get("reason")
    if not isinstance(reason, str):
        return None
    reason_stripped = reason.strip()
    if not reason_stripped:
        return None
    return ClarifyNeeded(reason=reason_stripped)


def _build_retrieval_plan(
    data: dict[str, object], max_specs: int, *, query: str
) -> RetrievalPlan:
    """Build a RetrievalPlan from ``data["specs"]``, capped at *max_specs*.

    Always returns at least one spec: an empty or all-junk list becomes the
    broad semantic fallback on *query*.
    """
    raw_specs = data.get("specs")
    if not isinstance(raw_specs, list):
        raw_specs = []

    planned_specs: list[PlannedSpec] = []
    for item in raw_specs:
        if not isinstance(item, dict):
            continue

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

    if not planned_specs:
        return build_broad_semantic_plan(
            query, rationale="fallback: broad semantic search"
        )

    # A model returning more specs than asked must not multiply retrieval passes
    # on a billable endpoint.
    capped = tuple(planned_specs[:max_specs])

    return RetrievalPlan(specs=capped, clarify=None)


def _str_list(value: object) -> list[str]:
    """Coerce an LLM-supplied list-shaped field into a list of strings.

    LLMs often emit a bare string where a list is expected (``"keywords":
    "invoice"``); iterating it would yield single characters, so a string
    becomes ``[value]``. Any other non-list becomes ``[]``.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _str_or_none(value: object) -> str | None:
    """Return a scalar *value* as a stripped string, or None when empty.

    A list or dict returns ``None`` rather than its ``repr``, so
    ``["npower", "EDF"]`` never becomes the filter ``"['npower', 'EDF']"``.
    """
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text if text else None
