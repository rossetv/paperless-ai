# Review lessons — recurring finding classes

Standing checks distilled from Large-Change-Workflow gate rounds. Apply these
when writing or reviewing specs, plans, and code in this repo — before a gate
does it for you. Living file: add a class when a finding recurs, sharpen one
when it sharpens, delete one that stops being true.

## Spec & plan gates

- **Grep-receipt every "X is in file Y" claim.** The single most-repeated
  finding across the spec and plan gates (3 rounds each) was invented or wrong
  harness/symbol locations — naming a helper in the wrong file, calling a
  function a "fixture", asserting a test path that did not exist. Any sentence
  in a spec or plan that locates a symbol, test, or fixture carries a
  `grep`-verified anchor, never a remembered one.
- **Lint and run the code a plan shows.** Extracting the plan's snippets and
  running `ruff` / `pytest` on them caught real defects cheaply — `F401` residue,
  wrong kwarg names, `caplog` where the project uses `capture_logs`. A plan's
  code blocks are code; check them like code.
- **A new early-return / skip branch must state its return value** wherever a
  downstream consumer switches on it. "Reuses the existing primitive" and
  "routes through the existing code path" are different claims — say which one
  is true.

## Fail-safe / untrusted-input code

- **Every parser gets an explicit malformed-input decision, and it fails
  closed.** A garbled probe row must *raise*, never silently read as "no signal".
  The gates repeatedly flagged fail-*open* parsers on untrusted PDF bytes; the
  safe direction here is to over-OCR, so any ambiguity resolves to "not
  born-digital".
- **A subprocess timeout must live in the read loop, not just `proc.wait()`.**
  The plan gate's one CRITICAL was a decorative timeout: a Poppler binary that
  spins with no output would hang a worker because the deadline sat only on
  `wait()`, not on a `select`-based read. Any subprocess over untrusted input
  needs a read-deadline **and** a hard output cap (decompression-bomb defence).

## Implementation review

- **A mocked test seam does not guard the real logic beneath it.** The
  max-vs-sum coverage invariant had a "test" that mocked `_probe_signals`, so it
  never exercised the parser it claimed to protect. For a load-bearing
  invariant, test the actual function against an input that would flip under the
  wrong variant — not a mock sitting above it.
- **Prefer a pair or a dataclass to a 3-tuple return** (CODE_GUIDELINES.md
  §5.8). A three-or-more positional unpack at the call site is a review finding
  on sight; the module usually already has a frozen dataclass to reach for.

## Public-repo hygiene

- **Sanitise before the *first* commit, not the last.** Host / topology / PII
  removed only in the tip commit still ships in the branch's earlier commits,
  and the whole history is pushed to the public repo. The secret-scan gate
  caught a topology string that had already been "sanitised" in the final
  commit — it survived in earlier ones. Deleting a line in a later commit does
  not clean git history; the fix is a history rewrite, and it is far cheaper to
  keep the value out from commit one. See [[public-repository]].

## Empirical calibration

- **Measurement beats an argued preference on a contested formula.** The
  max-vs-sum coverage choice was settled by re-running the detection probe
  against the operator's ground-truth corpus: the sum variant flipped a
  known born-digital doc to OCR, max held. When a ground-truth set exists,
  measure the decision — do not debate it.
