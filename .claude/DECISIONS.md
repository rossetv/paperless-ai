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

**Decision:** OpenAI defaults move to gpt-5.6-luna/terra (Sol selectable,
never default); reasoning-effort choices become the live-verified {none, low,
medium, high, xhigh}, with stored "minimal" coerced to "none"; OCR +
classifier run on the Flex service tier behind `OPENAI_FLEX_TIER` (default
on) with retry-until-done capacity-429 semantics; every OpenAI call names its
`service_tier` explicitly. Batch API, the Responses API migration, and any
embedding change are rejected for now.
**Why:** "max" is excluded from the reasoning-effort set — the docs list it
but the live API rejects it. Batch/Responses/embedding changes were weighed
and rejected — see spec sections D3/D10 for the trade-offs considered.
**Spec:** `.claude/specs/20260715-flex-and-56-models.md`
**Affects:** common/config, common/llm, ocr, classifier, search, web settings

## 2026-07-15 — Remove GATES.md's fulfilled reconciliation note

**Decision:** Delete the three-line note in `GATES.md` stating gates 9/10 were not yet
documented in `TESTING.md` — the same commit documents them there, fulfilling the note.
**Why:** The note was a self-scheduled reminder, not a gate; once fulfilled it would lie.
No gate row was removed or edited — the 10-gate table is untouched. Approved by: human
(operator, 2026-07-15), per the gate's removal-needs-a-record rule.
**Affects:** `.claude/GATES.md`, `.claude/docs/TESTING.md`

## 2026-07-15 — Migrate GATES.md to the canonical stanza grammar

**Decision:** Rewrite `GATES.md` from the ad-hoc table format (authored earlier today)
into the canonical stanza grammar from the config repo's `templates/kb/GATES.md` —
`### gate: <id>` stanzas with kind/why/added/mandated-by-human fields and fenced
commands, plus the template's standard anti-cheat and change-control sections.
**Why:** The kb-gate's push-time validator parses only the canonical grammar; the table
format read as "no gates declared" and blocked every push. All ten commands are
unchanged — this is a format migration, not a gate change. Approved by: human
(operator, 2026-07-15 — "approved", in response to the explicit rewrite proposal).
**Affects:** `.claude/GATES.md`

## 2026-07-15 — Correct the LLM-budget claim in CODE_GUIDELINES.md

**Decision:** Amend §14.3 and §10.6 — the "three LLM calls per query" ceiling becomes the
real formula `(2 + j) × (1 + SEARCH_MAX_REFINEMENTS)`, six at shipped defaults, citing
`search/core._max_llm_calls`.
**Why:** The judge gate plus the refinement loop made "three" false long before this
branch; the corrected code docstrings cross-referenced §14.3 and sent readers to the lie.
Human-owned law, edited only on explicit operator instruction: "You are allowed to edit
the CODE_GUIDELINES.md to fix this" (2026-07-15).
**Affects:** `CODE_GUIDELINES.md` §14.3, §10.6
