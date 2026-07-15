"""LLM document-relevance judge — the Layer-3 pre-synthesis screen.

The judge makes one LLM call on the cheap SEARCH_JUDGE_MODEL (falling back
through CLASSIFY_MODELS) and returns one :class:`~search.models.DocVerdict` per
candidate. It is recall-biased and fail-open: any failure — malformed, empty,
unparseable, all-models-failed — returns a verdict that keeps EVERY candidate
document (degraded=True), so a broken judge can only ever reduce the answer
model's context when it is confident, never block a real answer.
``judge()`` never raises.

All LLM calls go through ``OpenAIChatMixin._create_completion``
(CODE_GUIDELINES.md §8.1): the judge subclasses the mixin and inherits the
shared OpenAI singleton, the ``@retry`` backoff, and the ``llm_limiter``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

import structlog

from common.llm import OpenAIChatMixin, extract_json_object
from search.models import DocVerdict, JudgeCandidate, JudgeVerdict
from search.prompts import (
    JUDGE_SYSTEM_PROMPT,
    _judge_response_format,
    build_judge_user_message,
)

if TYPE_CHECKING:
    from common.config import Settings
    from common.llm import LlmCallUsage

log = structlog.get_logger(__name__)

#: Maximum length (characters) for a model-generated rationale string.
_MAX_REASON_CHARS = 200


def _parse_score(raw: object) -> float:
    """Coerce a raw model ``score`` into a clamped ``[0.0, 1.0]`` float.

    A missing, non-numeric, or boolean value defaults to ``0.0`` — the judge
    expressing no positive confidence — never trusting raw model output
    unchecked (CODE_GUIDELINES §10.4). A genuine number outside the unit range
    is clamped to the nearest bound. ``bool`` is rejected explicitly: it is an
    ``int`` subclass, so ``True`` would otherwise read as the score ``1.0``.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(raw)))


class RelevanceJudge(OpenAIChatMixin):
    """Decide which retrieved documents could plausibly answer the query.

    A pure function wrapped in a class for dependency injection; all state is in
    the injected ``settings``, so instances are safe to share across threads.

    Args:
        settings: Supplies SEARCH_JUDGE_MODEL and CLASSIFY_MODELS for the fallback
            chain, SEARCH_JUDGE_REASONING_EFFORT, SEARCH_JUDGE_RATIONALES, and
            MAX_RETRIES / MAX_RETRY_BACKOFF_SECONDS for the inherited retry
            decorator.
    """

    _STAT_KEYS: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        # ``self.settings`` is the attribute the @retry decorator reads via
        # duck-typing — it must not be renamed.
        self.settings = settings
        self._init_stats()

    @property
    def _provider(self) -> str:
        """Route the judge's chat call to the judge step's provider."""
        return self.settings.SEARCH_JUDGE_PROVIDER

    def judge(
        self,
        query: str,
        candidates: Sequence[JudgeCandidate],
        *,
        asker: str | None = None,
        today: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
    ) -> JudgeVerdict:
        """Return the relevant-document verdict for *query* over *candidates*.

        One LLM call on SEARCH_JUDGE_MODEL. Fail-open on every failure path:
        the returned verdict then keeps all candidate ids with ``degraded=True``.
        Never raises.

        Args:
            query: The user's original search query.
            candidates: The document-level candidates (id + best-chunk snippet).
            asker: Optional sanitised display name of the requesting user.
                When set, an identity line is added to the user message so the
                judge can resolve ownership — a document whose content belongs
                to the asker is treated as relevant to "my …" queries even when
                the title does not repeat their name.
            today: Today's date in YYYY-MM-DD form, or ``None``. When set, a
                date line is added to the user message so the judge can resolve
                relative temporal language.
            usage_sink: Optional list to receive one
                :class:`~common.llm.LlmCallUsage` record capturing the token
                usage for this call. Pass ``None`` to skip capture.
        """
        all_ids = frozenset(c.document_id for c in candidates)
        if not all_ids:
            # Nothing to judge — fail-open rather than emit an accidental bail.
            return JudgeVerdict(verdicts=(), degraded=True)

        include_reasons = self.settings.SEARCH_JUDGE_RATIONALES
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_judge_user_message(
                    query,
                    list(candidates),
                    include_reasons=include_reasons,
                    asker=asker,
                    today=today,
                ),
            },
        ]
        raw_content = self._complete_with_model_fallback(
            primary_model=self.settings.SEARCH_JUDGE_MODEL,
            messages=messages,
            # Fall back to CLASSIFY_MODELS only when the judge and classifier
            # share a provider — otherwise those models belong to a different
            # endpoint and would 404 on this stage's client (per-step providers).
            fallback_models=(
                self.settings.CLASSIFY_MODELS
                if self.settings.SEARCH_JUDGE_PROVIDER
                == self.settings.CLASSIFY_PROVIDER
                else ()
            ),
            log_event_prefix="judge",
            # reasoning_effort is OpenAI-only; omit it for a non-OpenAI judge.
            reasoning_effort=(
                self.settings.SEARCH_JUDGE_REASONING_EFFORT
                if self.settings.SEARCH_JUDGE_PROVIDER == "openai"
                else None
            ),
            response_format=_judge_response_format(self.settings),
            # Explicit standard tier on OpenAI — never flex here (a human is
            # waiting), and an explicit tier dodges the live-verified 401 on
            # tierless requests (spec D4). Omitted for non-OpenAI providers.
            service_tier=(
                "default" if self.settings.SEARCH_JUDGE_PROVIDER == "openai" else None
            ),
            usage_sink=usage_sink,
        )
        if raw_content is None:
            return self._fail_open(
                all_ids, reason="all models failed or returned empty content"
            )
        return self._parse_response(raw_content, all_ids, list(candidates))

    def _parse_response(
        self,
        raw: str,
        all_ids: frozenset[int],
        candidates: list[JudgeCandidate],
    ) -> JudgeVerdict:
        """Parse *raw* into a JudgeVerdict, failing open on any malformed shape.

        Bail (empty kept, not degraded) ONLY when the model returned an explicit
        verdict list AND every candidate's resolved ``keep`` is ``False``.

        Missing candidates (the model omitted a document id) default to
        ``keep=True`` with an empty reason — recall-biased safe default. Reason
        strings are capped at :data:`_MAX_REASON_CHARS`.
        """
        stripped = raw.strip()
        if not stripped:
            return self._fail_open(all_ids, reason="LLM returned empty content")
        try:
            data = extract_json_object(stripped)
        except json.JSONDecodeError:
            return self._fail_open(all_ids, reason="LLM response was not valid JSON")
        if not isinstance(data, dict):
            return self._fail_open(all_ids, reason="LLM response was not a JSON object")

        raw_verdicts = data.get("verdicts")
        if not isinstance(raw_verdicts, list):
            return self._fail_open(all_ids, reason="missing or non-list verdicts field")

        # Build a lookup from the model's verdicts, validating each entry.
        model_verdicts: dict[int, tuple[bool, str, float]] = {}
        for item in raw_verdicts:
            if not isinstance(item, dict):
                continue
            doc_id = item.get("document_id")
            keep = item.get("keep")
            reason = item.get("reason", "")
            if not isinstance(doc_id, int) or isinstance(doc_id, bool):
                continue
            if not isinstance(keep, bool):
                continue
            if not isinstance(reason, str):
                reason = ""
            # Cap reason length; never trust raw model text unchecked.
            reason = reason[:_MAX_REASON_CHARS]
            score = _parse_score(item.get("score"))
            if doc_id in all_ids:
                model_verdicts[doc_id] = (bool(keep), reason, score)

        # Build a DocVerdict for EVERY candidate. An omitted id defaults to
        # keep=True, "" reason, score 0.0 — recall-biased: the judge not
        # mentioning a doc is not an explicit drop. The score carries no gate
        # weight; it is used only for source ranking (Phase 3B).
        doc_verdicts: list[DocVerdict] = []
        for candidate in candidates:
            if candidate.document_id in model_verdicts:
                keep_flag, reason_str, score_value = model_verdicts[
                    candidate.document_id
                ]
            else:
                keep_flag, reason_str, score_value = True, "", 0.0
            doc_verdicts.append(
                DocVerdict(
                    document_id=candidate.document_id,
                    keep=keep_flag,
                    reason=reason_str,
                    score=score_value,
                )
            )

        return JudgeVerdict(verdicts=tuple(doc_verdicts), degraded=False)

    def _fail_open(self, all_ids: frozenset[int], reason: str) -> JudgeVerdict:
        """Return a keep-everything verdict and log a warning.

        Every fail-open verdict carries ``keep=True`` and ``score=1.0``. The
        score is set to full confidence so source ranking (Phase 3B) does not
        demote documents the judge could not evaluate — a degraded judge only
        ever loses precision, never blocks an answer.
        """
        log.warning("judge.degraded_to_fail_open", reason=reason)
        return JudgeVerdict(
            verdicts=tuple(
                DocVerdict(
                    document_id=i,
                    keep=True,
                    reason="(judge unavailable — kept by fail-open)",
                    score=1.0,
                )
                for i in sorted(all_ids)
            ),
            degraded=True,
        )
