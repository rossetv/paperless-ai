<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every command below must be verified to RUN
before it is written here; a gate that has never been run is not a gate.
NEVER cite a line number. Cite a file plus a stable, greppable anchor. -->
↑ [INDEX](INDEX.md)

# Gates — paperless-ai

<!-- This file is an operator's RUNBOOK, not documentation. TESTING.md explains how
testing is architected; this says how to CHECK the work and confirm it passes.
They are different at their souls. -->

## DO NOT CHEAT. NEVER BYPASS A GATE.

**A red gate means the work is not done. It does not mean the gate is wrong.**

The cheapest way to turn a red gate green is to edit this file and delete the gate.
That is cheating, and **it will not feel like cheating at the time** — it will feel
like *"this gate was stale anyway."* **That feeling is the failure mode, not a
finding.**

Adding a gate is cheap. **Removing or editing a gate requires a `/panel` — never a
single Claude's decision.** Log the outcome to `DECISIONS.md`.

**Never edit the thing a gate points at in order to make the gate pass.** Do not
delete or `.skip` a failing test. Do not gut a `package.json` target, a Makefile
rule, or a lint config. **The gate command is a pointer; hollowing out what it
points at is the same cheat wearing a better disguise** — and it is the one cheat
this file's machinery cannot detect, so it is on you.

Never `--no-verify`. Never skip. Never mark a check "not applicable" to avoid
running it. If you cannot make a gate pass, **stop and say so** — that is a
legitimate, respectable outcome. Silently weakening the standard is not.

**There is no override.** If work must ship red, a human pushes it themselves,
outside Claude.

## Changing gates

- **Add** — cheap, monocratic, no panel. Record `why`, date, provenance, model.
- **Remove or edit** — `/panel`, using the panel skill's hardened gate-removal
  brief; verdict enum `keep | fix-the-test | edit | remove`, default `keep`.
- **The human says "remove it"** — no panel; a human decision always overrides.
  The `DECISIONS.md` entry records provenance `human` and quotes the human's
  instruction verbatim.
- **Anti-drift:** a one-off unblock must never silently become a permanent
  deletion — propose re-adding immediately once unblocked.

## What is worth gating

Deterministic, fast, catches a real defect class, fails for one legible reason.
Check-only modes only — a gate must not mutate the working tree. Slow jobs are
CI's, not this file's.

## Mechanical gates

<!-- Run by kb-gate.sh Check 3 on every push and PR. Exit 0 = pass. One stanza
per gate. `id` is immutable — the removal tripwire keys on it.
Environment notes: python tools run from the repo venv (`pip install -r
requirements-dev.txt && pip install .`); 6 poppler-dependent OCR integration
tests skip silently without `pdftoppm` on PATH (`brew install poppler`) — a
known skip, not a failure. Coverage as CI enforces it, when touching
coverage-gated packages: `python -m pytest -q -n auto --cov=common --cov=ocr
--cov=classifier --cov=store --cov=indexer --cov=search
--cov-report=term-missing --cov-fail-under=70`. -->

### gate: python-tests
kind: mechanical
why: behavioural regressions anywhere in the Python tree — the whole suite, unit through e2e.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
python -m pytest -n auto
```

### gate: python-types
kind: mechanical
why: type errors that only surface at runtime in a daemon nobody is watching.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
mypy src
```

### gate: python-lint
kind: mechanical
why: lint defects and format drift; check-only, never rewrites.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
ruff check src tests && ruff format --check src tests
```

### gate: python-security
kind: mechanical
why: known-dangerous patterns (MEDIUM+ severity) in a codebase that handles operator credentials.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
bandit -r src/ -ll
```

### gate: web-types
kind: mechanical
why: TypeScript errors in the SPA; the build enforces this too, this fails faster.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
cd web && npm run typecheck
```

### gate: web-lint
kind: mechanical
why: eslint layer-boundary violations and stylelint literal-colour/size bans.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
cd web && npm run lint
```

### gate: web-tests-coverage
kind: mechanical
why: SPA behavioural regressions plus the coverage floor (91/83/91/91) CI enforces — plain `npm run test` measures nothing.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
cd web && npm run test:coverage
```

### gate: web-build
kind: mechanical
why: a bundle that will not build cannot ship; tsc + vite in one.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
cd web && npm run build
```

### gate: python-dep-audit
kind: mechanical
why: known-vulnerable Python dependencies; CI's dependency-audit job, runnable locally.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
pip-audit
```

### gate: web-dep-audit
kind: mechanical
why: known-vulnerable production JS dependencies (high+), matching CI's frontend audit step.
added: 2026-07-15 — monocratic (claude-fable-5)
mandated-by-human: no

```sh
cd web && npm audit --omit=dev --audit-level=high
```

## Semantic gates

<!-- Verified by the adversarial-reviewer agent — on OPUS, never a lesser model.
Use these ONLY for assertions no exit code can express. None declared yet. -->

## Retired

<!-- One line per retired id, at column 0: `- <id> — <YYYY-MM-DD>` where the
date is the DECISIONS.md entry recording the removal. An id listed here can
never be reused. Gate stanzas may not appear below this heading. -->
