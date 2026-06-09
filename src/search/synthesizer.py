"""LLM answer synthesiser — Stage 3 of the search pipeline.

The synthesiser makes one LLM call using the configured SEARCH_ANSWER_MODEL
(falling back through AI_MODELS on failure) and parses the JSON response into
either an ``Answered`` or a ``NeedsMore`` dataclass.

Design notes:
- No Pydantic; parsing follows the manual pattern from classifier/result.py
  (CODE_GUIDELINES.md §5.6).
- Prompt-injection safety (CODE_GUIDELINES.md §10.2): retrieved chunk texts
  are untrusted document content.  In the *user* message the question leads and
  the chunks follow, fenced inside a data block delimited by an unpredictable
  per-message nonce; the system prompt declares that everything between the
  nonce fences is data to be analysed, never instructions to be followed.  A
  chunk cannot reproduce the nonce, so it cannot forge the boundary (SRCH-01).
- ``mode="exploratory"`` allows the model to return NeedsMore when context is
  too thin.  ``mode="final"`` coerces the outcome to Answered — even on thin
  context the model must answer or state that nothing was found.
- On any bad LLM response: in ``"final"`` mode, degrades to Answered stating
  the answer could not be produced; in ``"exploratory"`` mode, degrades to
  NeedsMore with a generic adjustment.  Never raises on a bad LLM response.
- All LLM calls go through ``OpenAIChatMixin._create_completion``
  (CODE_GUIDELINES.md §8.1): the synthesiser subclasses the mixin and inherits
  the shared OpenAI singleton, the ``@retry`` exponential backoff, and the
  ``llm_limiter`` global concurrency limiter.  It iterates SEARCH_ANSWER_MODEL
  then AI_MODELS, mirroring ``classifier/provider.ClassificationProvider``.
- A failing model — whether a retry-exhausted retryable error or a
  non-retryable one (``AuthenticationError``, ``PermissionDeniedError``,
  ``NotFoundError``, ``BadRequestError``) — is caught as ``openai.APIError``
  and the next model is tried.  When every model fails the synthesiser
  degrades gracefully.  ``synthesise()`` therefore never raises.
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

log = structlog.get_logger(__name__)

# Fallback answer text used when the LLM returns unparseable content in final mode.
_FALLBACK_FINAL_ANSWER = (
    "No answer could be produced: the retrieved context did not yield "
    "a parseable response."
)

# Fallback adjustment used when the LLM returns unparseable content in exploratory mode.
_FALLBACK_EXPLORATORY_ADJUSTMENT = (
    "LLM response was unparseable; broadening the query may help."
)


class Synthesizer(OpenAIChatMixin):
    """Synthesises a prose answer from retrieved chunks via one LLM call.

    The synthesiser is a pure function wrapped in a class for dependency
    injection.  All state is in the injected ``settings``; Synthesizer
    instances are safe to share across threads.

    LLM calls go through the inherited ``OpenAIChatMixin._create_completion``,
    which owns the shared OpenAI client singleton, retry, and the concurrency
    limiter (CODE_GUIDELINES.md §8.1).

    Args:
        settings: Application settings; supplies SEARCH_ANSWER_MODEL and
            AI_MODELS for the fallback chain, plus MAX_RETRIES /
            MAX_RETRY_BACKOFF_SECONDS for the inherited retry decorator.
    """

    # The synthesiser keeps no stats; an empty tuple satisfies the mixin contract.
    _STAT_KEYS: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` is the attribute name the @retry decorator reads
        # via the HasRetrySettings protocol — it must not be renamed.
        self.settings = settings
        self._init_stats()

    def synthesise(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        mode: SearchMode,
    ) -> AnswerOutcome:
        """Synthesise an answer for *query* using the retrieved *chunks*.

        Makes one LLM call using SEARCH_ANSWER_MODEL, falling back through
        AI_MODELS on any API error.  On any parse failure or exhausted
        fallback, degrades gracefully based on *mode*.

        Args:
            query: The user's original search query.
            chunks: Retrieved chunks to use as context.  Each chunk is labelled
                with its source document id so the model can cite [n] references.
            mode: Either ``"exploratory"`` (the model may return NeedsMore) or
                ``"final"`` (the model must return Answered — coerced if needed).

        Returns:
            An ``Answered`` or ``NeedsMore`` dataclass.  Never raises.
        """
        labelled_chunks = [(chunk.document_id, chunk.text) for chunk in chunks]
        is_final = mode == "final"

        system_prompt = SYNTHESISER_SYSTEM_PROMPT
        user_message = build_synthesiser_user_message(
            query=query,
            labelled_chunks=labelled_chunks,
            final=is_final,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_ANSWER_MODEL,
            messages=messages,
            fallback_models=self.settings.AI_MODELS,
            log_event_prefix="synthesiser",
            reasoning_effort=self.settings.SEARCH_ANSWER_REASONING_EFFORT,
            response_format=_synthesiser_response_format(self.settings),
        )
        if raw_content is None:
            return self._degrade(
                mode, reason="all models failed or returned empty content"
            )

        return self._parse_response(query, raw_content, mode=mode)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_response(
        self, query: str, raw: str, *, mode: SearchMode
    ) -> AnswerOutcome:
        """Parse *raw* into an AnswerOutcome, degrading gracefully on any error.

        Args:
            query: Original user query — used in logging.
            raw: Raw text returned by the LLM.
            mode: ``"exploratory"`` or ``"final"``.

        Returns:
            An ``Answered`` or ``NeedsMore`` dataclass, or the safe degraded
            fallback.
        """
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
            try:
                answer = str(data.get("answer") or "").strip()
                citations = tuple(int(cid) for cid in (data.get("citations") or []))
                return Answered(answer=answer, citations=citations)
            except (TypeError, ValueError) as exc:
                return self._degrade(
                    mode, reason=f"answered payload had unexpected structure: {exc}"
                )

        if outcome_type == "needs_more":
            adjustment = str(data.get("adjustment") or "").strip()
            if mode == "final":
                # In final mode, NeedsMore is not allowed — coerce to Answered.
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
        """Return a safe fallback outcome and log a warning.

        In ``"final"`` mode, returns an ``Answered`` stating the answer could
        not be produced.  In ``"exploratory"`` mode, returns a ``NeedsMore``
        with a generic broadening suggestion — the pipeline will either refine
        or eventually call a final-mode synthesise.

        Args:
            mode: ``"exploratory"`` or ``"final"``.
            reason: Human-readable explanation for the degradation.

        Returns:
            A safe ``AnswerOutcome``.
        """
        log.warning(
            "synthesiser.degraded_to_fallback",
            reason=reason,
            mode=mode,
        )
        if mode == "final":
            return Answered(answer=_FALLBACK_FINAL_ANSWER, citations=())
        return NeedsMore(adjustment=_FALLBACK_EXPLORATORY_ADJUSTMENT)
