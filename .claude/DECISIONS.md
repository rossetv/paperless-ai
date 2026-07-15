# Decisions

<!-- Claude-maintained, append-only. Entries are never edited or deleted; a
reversal gets a new dated entry that names what it supersedes. Every entry
starts with a heading of the form:

    ## YYYY-MM-DD — <short decision title>

kb-context.sh extracts titles by that pattern — this format and that script
are a coupled contract; change them only together, in the CLAUDE repo.

Entry body shape (Spec/Affects/Supersedes lines only when applicable):

    **Decision:** <what was decided>
    **Why:** <the reason — trade-offs considered>
    **Spec:** .claude/specs/<file>.md
    **Affects:** <KB doc paths this decision touches, comma-separated>
    **Supersedes:** <date/title of the earlier entry, only if a reversal>

Delete nothing above when appending; append new entries at the end of file. -->

## 2026-07-15 — Adopt GPT-5.6, refresh reasoning efforts, add Flex tier

**Spec:** `.claude/specs/20260715-flex-and-56-models.md`
**Affects:** common/config, common/llm, ocr, classifier, search, web settings

OpenAI defaults move to gpt-5.6-luna/terra (Sol selectable, never default);
reasoning-effort choices become the live-verified {none, low, medium, high,
xhigh} with stored "minimal" coerced to "none"; OCR + classifier run on the
Flex service tier behind OPENAI_FLEX_TIER (default on) with
retry-until-done capacity-429 semantics; every OpenAI call names its
service_tier explicitly. "max" excluded — docs list it, live API rejects it.
Batch API, Responses API migration, and any embedding change rejected — see
spec D3/D10.
