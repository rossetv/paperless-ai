"""LLM answer synthesiser: the final stage of the search pipeline.

One call to SEARCH_ANSWER_MODEL (falling back through CLASSIFY_MODELS) whose
JSON response is parsed into an ``Answered`` or ``NeedsMore``.

- Retrieved chunks are untrusted. The question leads the user message and the
  chunks follow inside a block fenced by a per-message nonce; the system prompt
  says everything inside the fences is data, never instructions. A chunk cannot
  reproduce the nonce, so it cannot forge the boundary.
- ``mode="exploratory"`` may return NeedsMore when context is thin;
  ``mode="final"`` always yields Answered, even if only to say nothing was found.
- Every failure (each model erroring, or an unparseable response) degrades to a
  safe outcome for the mode, so ``synthesise()`` never raises.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

import structlog

from common.llm import OpenAIChatMixin, extract_json_object
from search.models import (
    Answered,
    AnswerOutcome,
    NeedsMore,
    RetrievedChunk,
    SearchMode,
)
from search.prompts import (
    SYNTHESISER_SYSTEM_PROMPT,
    _synthesiser_response_format,
    build_synthesiser_user_message,
)
from search.text import ADJUSTMENT_LOG_PREFIX_CHARS, QUERY_LOG_PREFIX_CHARS

if TYPE_CHECKING:
    from common.config import Settings
    from common.llm import LlmCallUsage

log = structlog.get_logger(__name__)

# Per attempt: a hung hosted call is retried while the person is still waiting.
_ANSWER_TIMEOUT_SECONDS = 60

_FALLBACK_FINAL_ANSWER = (
    "No answer could be produced: the retrieved context did not yield "
    "a parseable response."
)

_FALLBACK_EXPLORATORY_ADJUSTMENT = (
    "LLM response was unparseable; broadening the query may help."
)


class Synthesizer(OpenAIChatMixin):
    """Synthesises a prose answer from retrieved chunks via one LLM call.

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
        """Route the synthesiser's chat call to the answer step's provider."""
        return self.settings.SEARCH_ANSWER_PROVIDER

    def synthesise(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        mode: SearchMode,
        asker: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
        documents_by_id: dict[int, tuple[str | None, str | None]] | None = None,
    ) -> AnswerOutcome:
        """Synthesise an answer for *query* from *chunks*. Never raises.

        Args:
            asker: The sanitised asker identity; when set, first-person
                references in the query resolve to it.
            usage_sink: Optional list that receives this call's token usage.
            documents_by_id: Optional ``{document_id: (title, created)}`` from
                the index (not chunk text), used to label each chunk with its
                document's title and date. Missing documents get a bare ``[id]``.
        """
        labelled_chunks = [(chunk.document_id, chunk.text) for chunk in chunks]
        is_final = mode == "final"

        system_prompt = SYNTHESISER_SYSTEM_PROMPT
        user_message = build_synthesiser_user_message(
            query=query,
            labelled_chunks=labelled_chunks,
            final=is_final,
            asker=asker,
            documents_by_id=documents_by_id,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_ANSWER_MODEL,
            messages=messages,
            # Fall back to CLASSIFY_MODELS only when the answer and classifier
            # share a provider — otherwise those models belong to a different
            # endpoint and would 404 on this stage's client (per-step providers).
            fallback_models=(
                self.settings.CLASSIFY_MODELS
                if self.settings.SEARCH_ANSWER_PROVIDER
                == self.settings.CLASSIFY_PROVIDER
                else ()
            ),
            log_event_prefix="synthesiser",
            # reasoning_effort is OpenAI-only; omit it for a non-OpenAI answer.
            reasoning_effort=(
                self.settings.SEARCH_ANSWER_REASONING_EFFORT
                if self.settings.SEARCH_ANSWER_PROVIDER == "openai"
                else None
            ),
            response_format=_synthesiser_response_format(self.settings),
            # Explicit standard tier on OpenAI — never flex here (a human is
            # waiting), and an explicit tier dodges the live-verified 401 on
            # tierless requests. Omitted for non-OpenAI providers.
            service_tier=(
                "default" if self.settings.SEARCH_ANSWER_PROVIDER == "openai" else None
            ),
            # Local models can legitimately need the full REQUEST_TIMEOUT.
            timeout=(
                min(self.settings.REQUEST_TIMEOUT, _ANSWER_TIMEOUT_SECONDS)
                if self.settings.SEARCH_ANSWER_PROVIDER == "openai"
                else None
            ),
            usage_sink=usage_sink,
        )
        if raw_content is None:
            return self._degrade(
                mode, reason="all models failed or returned empty content"
            )

        return self._parse_response(query, raw_content, mode=mode)

    def _parse_response(
        self, query: str, raw: str, *, mode: SearchMode
    ) -> AnswerOutcome:
        """Parse *raw* into an AnswerOutcome, degrading gracefully on any error."""
        stripped = raw.strip()
        if not stripped:
            return self._degrade(mode, reason="LLM returned empty content")

        try:
            data = extract_json_object(stripped)
        except json.JSONDecodeError:
            return self._degrade(mode, reason="LLM response was not valid JSON")

        if not isinstance(data, dict):
            return self._degrade(mode, reason="LLM response was not a JSON object")

        outcome_type = data.get("outcome")

        if outcome_type == "answered":
            raw_answer = data.get("answer")
            if not isinstance(raw_answer, str):
                return self._degrade(
                    mode,
                    reason=f"answered payload 'answer' is not a string: {type(raw_answer).__name__}",
                )
            answer = raw_answer.strip()
            raw_citations = data.get("citations")
            cit_list = raw_citations if isinstance(raw_citations, list) else []
            # Skip citations that are not ints (e.g. "n/a", null): one junk
            # element must not discard a valid answer.
            citations: tuple[int, ...] = tuple(
                int(c)
                for c in cit_list
                if isinstance(c, (int, str)) and str(c).strip().lstrip("-").isdigit()
            )
            return Answered(answer=answer, citations=citations)

        if outcome_type == "needs_more":
            raw_adjustment = data.get("adjustment")
            if not isinstance(raw_adjustment, str):
                return self._degrade(
                    mode,
                    reason=f"needs_more payload 'adjustment' is not a string: {type(raw_adjustment).__name__}",
                )
            adjustment = raw_adjustment.strip()
            if mode == "final":
                log.warning(
                    "synthesiser.needs_more_in_final_mode",
                    query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                    adjustment=adjustment[:ADJUSTMENT_LOG_PREFIX_CHARS],
                )
                return Answered(
                    answer=(
                        "No relevant information was found in the document archive "
                        "to answer this question."
                    ),
                    citations=(),
                )
            return NeedsMore(adjustment=adjustment)

        return self._degrade(
            mode, reason=f"LLM response had unknown outcome type: {outcome_type!r}"
        )

    def _degrade(self, mode: SearchMode, reason: str) -> AnswerOutcome:
        """Log *reason* and return the safe fallback outcome for *mode*."""
        log.warning(
            "synthesiser.degraded_to_fallback",
            reason=reason,
            mode=mode,
        )
        if mode == "final":
            return Answered(answer=_FALLBACK_FINAL_ANSWER, citations=())
        return NeedsMore(adjustment=_FALLBACK_EXPLORATORY_ADJUSTMENT)
