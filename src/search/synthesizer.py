"""LLM answer synthesiser — Stage 3 of the search pipeline.

The synthesiser makes one LLM call using the configured SEARCH_ANSWER_MODEL
(falling back through AI_MODELS on failure) and parses the JSON response into
either an ``Answered`` or a ``NeedsMore`` dataclass.

Design notes:
- No Pydantic; parsing follows the manual pattern from classifier/result.py
  (CODE_GUIDELINES.md §5.6).
- Prompt-injection safety (CODE_GUIDELINES.md §10.2): retrieved chunk texts
  are untrusted document content.  They are placed in the *user* message below
  an explicit data delimiter; the system prompt declares that everything below
  the delimiter is data to be analysed, never instructions to be followed.
  This mirrors the defensive structure in ocr/prompts.py.
- ``mode="exploratory"`` allows the model to return NeedsMore when context is
  too thin.  ``mode="final"`` coerces the outcome to Answered — even on thin
  context the model must answer or state that nothing was found.
- On any bad LLM response: in ``"final"`` mode, degrades to Answered stating
  the answer could not be produced; in ``"exploratory"`` mode, degrades to
  NeedsMore with a generic adjustment.  Never raises on a bad LLM response.
- The llm_client is the OpenAI-compatible client injected by the caller; the
  synthesiser calls llm_client.chat.completions.create(...) directly, iterating
  through AI_MODELS on OpenAI API errors (mirroring the planner's fallback).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

import openai
import structlog

from common.llm import unique_models
from search.models import Answered, AnswerOutcome, NeedsMore, RetrievedChunk
from search.prompts import build_synthesiser_system_prompt, build_synthesiser_user_message

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

# Fallback answer text used when the LLM returns unparseable content in final mode.
_FALLBACK_FINAL_ANSWER = (
    "No answer could be produced: the retrieved context did not yield "
    "a parseable response."
)

# Fallback adjustment used when the LLM returns unparseable content in exploratory mode.
_FALLBACK_EXPLORATORY_ADJUSTMENT = (
    "LLM response was unparseable; broadening the query may help."
)


class Synthesizer:
    """Synthesises a prose answer from retrieved chunks via one LLM call.

    The synthesiser is a pure function wrapped in a class for dependency
    injection.  All state is in the injected ``settings`` and ``llm_client``;
    Synthesizer instances are safe to share across threads.

    Args:
        settings: Application settings; supplies SEARCH_ANSWER_MODEL and
            AI_MODELS for the fallback chain.
        llm_client: An OpenAI-compatible client (``openai.OpenAI`` or a mock
            in tests).  Must expose ``chat.completions.create``.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        self._settings = settings
        self._llm_client = llm_client

    def synthesise(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        mode: str,
    ) -> AnswerOutcome:
        """Synthesise an answer for *query* using the retrieved *chunks*.

        Makes one LLM call using SEARCH_ANSWER_MODEL, falling back through
        AI_MODELS on retryable API errors.  On any parse failure or exhausted
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

        system_prompt = build_synthesiser_system_prompt()
        user_message = build_synthesiser_user_message(
            query=query,
            labelled_chunks=labelled_chunks,
            final=is_final,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        raw_content = self._call_llm_with_fallback(query, messages)
        if raw_content is None:
            return self._degrade(mode, reason="all models failed or returned empty content")

        return self._parse_response(query, raw_content, mode=mode)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm_with_fallback(
        self, query: str, messages: list[dict[str, str]]
    ) -> str | None:
        """Try SEARCH_ANSWER_MODEL first, then each model in AI_MODELS.

        Returns the raw text content from the first successful call, or
        None if every model fails.

        The primary model (SEARCH_ANSWER_MODEL) is tried first.  If it is
        already in AI_MODELS it is not tried twice — unique_models deduplicates
        the combined list while preserving insertion order.
        """
        primary = self._settings.SEARCH_ANSWER_MODEL
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
                    "synthesiser.model_failed",
                    model=model,
                    error=str(exc),
                    query_prefix=query[:60],
                )
                continue
            except openai.BadRequestError as exc:
                # A 400 is not recoverable by retrying the same query; skip
                # this model rather than crashing the synthesiser.
                log.warning(
                    "synthesiser.model_rejected_request",
                    model=model,
                    error=str(exc),
                    query_prefix=query[:60],
                )
                continue

        return None

    def _parse_response(self, query: str, raw: str, *, mode: str) -> AnswerOutcome:
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
            data = _extract_json(stripped)
        except (json.JSONDecodeError, ValueError):
            return self._degrade(mode, reason="LLM response was not valid JSON")

        if not isinstance(data, dict):
            return self._degrade(mode, reason="LLM response was not a JSON object")

        outcome_type = data.get("outcome")

        if outcome_type == "answered":
            try:
                answer = str(data.get("answer") or "").strip()
                citations = tuple(
                    int(cid) for cid in (data.get("citations") or [])
                )
                return Answered(answer=answer, citations=citations)
            except (TypeError, ValueError) as exc:
                return self._degrade(mode, reason=f"answered payload had unexpected structure: {exc}")

        if outcome_type == "needs_more":
            adjustment = str(data.get("adjustment") or "").strip()
            if mode == "final":
                # In final mode, NeedsMore is not allowed — coerce to Answered.
                log.warning(
                    "synthesiser.needs_more_in_final_mode",
                    query_prefix=query[:60],
                    adjustment=adjustment[:120],
                )
                return Answered(
                    answer=(
                        "No relevant information was found in the document archive "
                        "to answer this question."
                    ),
                    citations=(),
                )
            return NeedsMore(adjustment=adjustment)

        return self._degrade(mode, reason=f"LLM response had unknown outcome type: {outcome_type!r}")

    def _degrade(self, mode: str, reason: str) -> AnswerOutcome:
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
