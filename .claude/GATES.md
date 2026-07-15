<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md.
The definition of "done" in this repo: every gate below green before a PR is
opened or work is declared complete. Removing or editing a gate requires a
/panel and a DECISIONS.md entry; adding one is free. -->
↑ [INDEX](INDEX.md)

# paperless-ai — Gates

Run from the repo root unless stated. All must pass.

| # | Gate | Command |
|---|------|---------|
| 1 | Python tests | `python -m pytest -n auto` |
| 2 | Types | `mypy src` |
| 3 | Lint | `ruff check src tests && ruff format --check src tests` |
| 4 | Security | `bandit -r src/ -ll` |
| 5 | Web types | `cd web && npm run typecheck` |
| 6 | Web lint | `cd web && npm run lint` |
| 7 | Web tests + coverage floor | `cd web && npm run test:coverage` |
| 8 | Web build | `cd web && npm run build` |
| 9 | Python dependency audit | `pip-audit` |
| 10 | Web dependency audit | `cd web && npm audit --omit=dev --audit-level=high` |

Coverage as CI enforces it (gate 1 alternative when touching coverage-gated
packages): `python -m pytest -q -n auto --cov=common --cov=ocr --cov=classifier
--cov=store --cov=indexer --cov=search --cov-report=term-missing
--cov-fail-under=70`.

Known skip: 6 poppler-dependent OCR integration tests skip silently without
`pdftoppm` on PATH (`brew install poppler`).

Gates 9 and 10 are not yet documented in `.claude/docs/TESTING.md` —
kb-updater will reconcile that doc on the next push.
