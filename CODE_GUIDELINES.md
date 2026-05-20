# Engineering Guidelines

> This document is for everyone who writes, reviews, or operates code in the
> paperless-ai repository. It is **canonical**: the rules below are the standard of
> care for the codebase, and a violation is a code-review blocker — not a judgement
> call. Propose changes in a pull request whose description names the rule, the
> rationale, and the alternative considered; the same standards that govern code
> govern this file. The spirit of the document is short: prefer boring code, narrow
> public surfaces, stateless daemons over one shared store, and errors designed at
> the same time as the success path. When two of those tug against each other, the
> values in [§1](#1-philosophy) decide.

> **Scope.** paperless-ai is two things in one repository: a set of headless Python
> daemons that add AI OCR, classification, and semantic indexing to Paperless-ngx,
> and a TypeScript/React search application that queries the index. Sections 1–11
> and 13–17 govern the Python backend; [§12](#12-frontend-architecture) governs the
> `web/` frontend. Both halves are held to the same bar.

> **Current standard for new code; honest about the old.** The existing daemons
> (`src/common`, `src/ocr`, `src/classifier`) already follow most of what is below —
> structured logging, frozen dataclasses, retry-wrapped I/O, a mirrored test tree.
> The `src/store`, `src/indexer`, `src/search`, and `web/` subsystems are held to
> every rule here from their first commit. Where an existing file diverges, the
> divergence is fixed in the PR that next touches it — not left to rot, not used as
> licence to add more.

> **British English everywhere.** Every identifier, comment, docstring, log event,
> commit message, and document in this repository uses British spelling — `colour`,
> `behaviour`, `organise`, `analyse`, `normalise`, `cancelled`. No exceptions. A
> `color` in a CSS token or a `normalize_` in a function name is a review nit.

## TL;DR — the ten rules most often violated

1. All Paperless HTTP goes through `PaperlessClient`; all LLM calls go through the
   `common/llm` wrapper; all embeddings through `common/embeddings`. A bare `httpx`
   or `openai` call outside those three modules is the blocker
   ([§8.1](#81-outbound-io-goes-through-the-shared-clients)).
2. The store is the only database. `src/store/` owns every `sqlite3` call and every
   line of SQL; nothing else imports `sqlite3` ([§9.1](#91-the-store-owns-all-sql)).
3. Parameter-substitute every SQL value; no f-string SQL, ever
   ([§9.5](#95-parameter-substitute-always)).
4. `from __future__ import annotations` and full type signatures on every public
   function ([§5.1](#51-public-functions-are-fully-typed)).
5. `raise NewError(...) from original` is mandatory when re-raising
   ([§6.3](#63-raise-x-from-original-is-mandatory)).
6. `except Exception:` only at the documented outer-boundary sites, each with a
   `# rationale:` comment ([§6.4](#64-except-exception-is-reserved-for-outer-boundaries)).
7. Never log a secret — Paperless token, OpenAI key, API key
   ([§7.4](#74-never-log-secrets)).
8. Frontend: no hardcoded design value. Colours, sizes, spacing, radii come from
   `tokens.css` only; a hex literal in a component is the blocker
   ([§12.4](#124-design-tokens-are-the-only-source-of-design-values)).
9. Frontend: imports flow downward through the layer stack only. A `pages/` file
   importing a primitive directly, or writing CSS, fails CI
   ([§12.3](#123-the-layer-stack-and-its-one-rule)).
10. Files over 500 lines and functions over 60 lines need a written `# rationale:`
    or they get split ([§3.1](#31-hard-limits)).

## 1. Philosophy

These are the values that survive every refactor. Style guides change; values do
not. When two rules in this document appear to conflict, the value below that the
rules serve wins.

### 1.1 Read like plain English

Code is read ten times for every time it is written. A function whose one-line
summary needs the word "and" is doing two things and must be split. A condition
that needs a comment to be understood must be lifted into a named predicate. The
reader's working memory is the scarcest resource in the system; spend everything
else first.

```python
# Bad — the summary needs "and": fetch the document AND embed it.
def fetch_and_embed(document_id: int) -> list[Chunk]: ...

# Good — two intent-revealing names, each does one thing.
def fetch_document(document_id: int) -> Document: ...
def embed_chunks(chunks: Iterable[Chunk]) -> list[EmbeddedChunk]: ...
```

### 1.2 Boring beats clever

Reach for the standard library before a third-party helper, and a third-party
helper before a custom abstraction. `dataclasses`, `pathlib`, `hashlib`,
`concurrent.futures`, `sqlite3` — these are not consolation prizes. A clever
metaclass saves three lines and costs every future reader twenty minutes.
Cleverness is a tax paid by people who did not write the code.

A violation: a hand-rolled retry loop when `common/retry.py`'s `@retry` decorator
already does exponential backoff with jitter.

### 1.3 Every line is a liability

Code is debt against future change. The default move when reviewing a diff is
*delete*, then *abstract*, then *write*. A new helper must replace at least two
existing call sites or be on a clear path to doing so within the same PR.
Speculative generality — parameters no caller supplies, hooks no caller registers —
is debt with no upside.

### 1.4 Errors are designed, not caught

An exception is a designed signal between the place that knows the failure shape
and the place that knows how to react. Exception types live close to the code that
raises them. A bare `except Exception:` is almost always a bug — see
[§6](#6-errors).

### 1.5 Tests are the README for behaviour

A new contributor must be able to read the test file for a module and understand
what the module promises. Test names describe behaviour, not implementation. A test
that breaks when an internal helper is renamed is a bad test; a test that breaks
when a documented behaviour changes is a great test. See [§11](#11-testing).

### 1.6 Names carry domain language

Paperless-ngx has *documents*, *correspondents*, *document types*, *tags*,
*content*. This project adds *chunks*, *embeddings*, *the index*, *the store*,
*reconciliation*, *query plans*, *retrieval*, *synthesis*, *source documents*,
*facets*. These are domain words. A function called `process(thing)` discards the
precise word the user, the database, and the test all share. Discovering the right
word is part of the work.

### 1.7 Module boundaries are contracts, not suggestions

A package's public surface is its contract. The dependency arrows in
[§2](#2-module-taxonomy) (backend) and [§12.3](#123-the-layer-stack-and-its-one-rule)
(frontend) are not aspirational; an import that violates them is a code-review
blocker even if it works. A search component reaching into `indexer/` internals, or
a `pages/` file importing a styling primitive, fails review.

### 1.8 Comments answer "why", never "what"

If the *what* needs explaining, rename the function or extract a helper. The *why*
— the non-obvious constraint, the upstream quirk, the domain rule — belongs in a
comment.

```python
# Bad — restates the obvious.
# increment the counter
indexed += 1

# Good — names the invariant.
# Count after the upsert transaction commits; a crash before this line must
# re-index the document next cycle, never silently skip it.
indexed += 1
```

### 1.9 Premature abstraction is worse than duplication

Two call sites that *look* alike are not yet a pattern. Three is the threshold for
extracting a helper. A premature base class or generic protocol locks in the wrong
axis of variation; deleting it later is harder than deleting duplication.

A violation: an `AbstractDaemon` base class introduced "so future daemons share
code" when `common/daemon_loop.py`'s `run_polling_threadpool` — a plain function
the OCR, classifier, and indexer daemons all call — already is the shared shape.

### 1.10 Public API is small by default

Every public name is a promise. Default to private (leading underscore); promote to
public only when a caller outside the module needs it and the contract is
documented.

### 1.11 Fail closed, fail loud

A missing required environment variable stops the process at startup — it does not
default to something plausible. An embedding-model mismatch wipes and rebuilds the
chunk tables loudly — it does not silently serve incomparable vectors. A refused
operation can be retried; a silent corruption cannot be undone.

### 1.12 Stateless daemons, one store, one writer

The OCR and classifier daemons are stateless: all their state lives in Paperless-ngx
tags, and they are safe to run as multiple instances. The **store is the single
source of truth** for the search index. The **indexer is its only writer** — exactly
one indexer process runs. The search server — one process hosting the HTTP API, the
Web UI, and the MCP endpoint — is a read-only consumer.
Drift between "the indexer is the sole writer" and a second process writing to the
store is a class of latent corruption we refuse to accept. New shared state either
lives in the store (with the indexer as writer) or is documented as in-process and
single-instance.

## 2. Module Taxonomy

The backend has four layers. Imports flow downward only; an upward or sideways
cross-package import is a review-blocker defect. The diagram is the contract.

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Interfaces      search/api.py   search/mcp_server.py        │
   └───────────────────────────────┬─────────────────────────────┘
                                    │
                                    ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌───────────────┐
   │  search/         │   │  indexer/        │   │  ocr/         │
   │  agentic pipeline│   │  reconcile daemon│   │  classifier/  │
   │  (read side)     │   │  (write side)    │   │  (tag daemons)│
   └────────┬─────────┘   └────────┬─────────┘   └───────┬───────┘
            │ read                 │ write               │
            ▼                      ▼                     │
   ┌─────────────────────────────────────────┐           │
   │  store/   SQLite + sqlite-vec + FTS5     │           │
   │  schema · migrations · reader · writer   │           │
   └────────────────────┬────────────────────┘           │
                        │                                 │
                        ▼                                 ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  common/   config · paperless · llm · embeddings · retry ·   │
   │  daemon_loop · tags · claims · bootstrap · shutdown ·        │
   │  concurrency · preflight · logging_config · constants        │
   └─────────────────────────────────────────────────────────────┘
```

### 2.1 `common/`

**Purpose.** Shared infrastructure used by every daemon and the search side:
configuration, the Paperless API client, the LLM and embedding wrappers, retry
logic, the polling loop, tag operations, structured logging.

**Allowed deps.** Standard library, the project's third-party runtime dependencies
(`httpx`, `openai`, `structlog`, `Pillow`, `pdf2image`). No imports from any other
internal package — `common` is the leaf.

**Forbidden patterns.** No imports from `store/`, `ocr/`, `classifier/`,
`indexer/`, or `search/`. No `sqlite3`. No FastAPI. No business logic specific to
one daemon.

### 2.2 `store/`

**Purpose.** The SQLite search index: schema definition, migrations, the write API
(`StoreWriter`), and the read API (`StoreReader`). Owns every `sqlite3` call and
every line of SQL in the codebase.

**Allowed deps.** `sqlite3`, `sqlite-vec`, `common/`.

**Forbidden patterns.** No imports from `indexer/`, `search/`, or the daemons. No
HTTP. No LLM calls. No business logic — the store persists and queries; it does not
decide what to persist. See [§9](#9-the-store).

### 2.3 `ocr/` and `classifier/`

**Purpose.** The two tag-driven processing daemons. OCR transcribes document pages
via a vision model; the classifier enriches document metadata via an LLM.

**Allowed deps.** `common/`. **Not `store/`** — these daemons are tag-driven and
hold no index state.

**Forbidden patterns.** No FastAPI. No `sqlite3`. No imports from `indexer/` or
`search/`.

### 2.4 `indexer/`

**Purpose.** The write side. A daemon that reconciles Paperless-ngx against the
store: chunk new and changed documents, embed the chunks, upsert them, prune
deleted documents.

**Allowed deps.** `store/` (the `StoreWriter`), `common/`.

**Forbidden patterns.** No FastAPI. No imports from `search/`. The indexer never
reads the store for query purposes — it reads index *state* (`get_index_state`) to
drive reconciliation, nothing more.

### 2.5 `search/`

**Purpose.** The read side. The agentic search pipeline — plan, retrieve, refine,
synthesise — and the two interface processes that expose it.

**Allowed deps.** `store/` (the `StoreReader`), `common/`.

**Forbidden patterns.** `search/` core (the pipeline) imports no FastAPI and no MCP
SDK — those belong only in `search/api.py` and `search/mcp_server.py` respectively.
The pipeline is a pure library. No imports from `indexer/` or the daemons.

**Subpackages and modules.**

- `search/core.py` — orchestrates the pipeline; the only public entry points are
  `answer()` and `retrieve()`.
- `search/planner.py`, `retriever.py`, `synthesizer.py` — the pipeline stages, each
  a discrete unit taking its dependencies (LLM client, store reader) by injection.
- `search/api.py` — the FastAPI app. The only module that imports `fastapi`.
- `search/mcp_server.py` — the MCP server. The only module that imports `mcp`.

### 2.6 Cross-package rules

1. `common/` imports nothing from another internal package.
2. `store/` imports only `common/`.
3. `ocr/`, `classifier/` import only `common/`.
4. `indexer/` imports `store/` and `common/`.
5. `search/` imports `store/` and `common/`. The pipeline never imports `fastapi`
   or `mcp`; only the two interface modules do.
6. No package imports a daemon (`ocr`, `classifier`, `indexer`) or `search`,
   except the interface modules importing the `search` pipeline.
7. A new top-level package needs a documented purpose, allowed-deps list, and
   forbidden patterns added to this section in the same PR.

## 3. File Organisation

### 3.1 Hard limits

- **Files: target 300 lines, ceiling 500.** Above 500 a file is no longer
  scannable in one screen-pair. The fix is *always* to extract a sibling module or
  promote the file to a package, never to keep growing.
- **Functions: target 30 lines, ceiling 60.** The count is **executable body
  lines** — it excludes the signature, decorators, the docstring, and blank lines.
- **Imports: max 30 imported names per file.** `from x import A, B` counts as two.

Exceptions require a one-line `# rationale:` comment explaining why no decomposition
is possible — a file header at the top, or immediately above the `def`. "It would
be awkward" is not a rationale. This in-file `# rationale:` is the single canonical
carve-out mechanism; there is no separate list.

The same limits apply to the frontend: a `.tsx` or `.ts` file over 500 lines, a
function or component over 60 body lines, needs a `// rationale:` comment.

### 3.2 One concept per file

A file is named for the *one* concept it owns. `chunker.py` splits text into
chunks; `reconciler.py` diffs Paperless against the store; `planner.py` builds a
query plan. A file called `utils.py`, `helpers.py`, or `misc.py` is a code smell —
its absence of a topic is the topic.

### 3.3 When you approach the ceiling, prefer a package

Sibling-dump (`foo.py` → `foo.py` + `foo_helpers.py`) loses the navigability the
file boundary buys. Promote to a package with a thin re-export `__init__.py` and
private `_`-prefixed internals.

### 3.4 Imports

Three blocks, in order, separated by a single blank line: standard library,
third-party, first-party. `from __future__ import annotations` is mandatory in
every new Python module ([§5](#5-type-system--data-shapes)). Cross-package imports
are absolute; relative imports are allowed only for intra-package internals.
Wildcard imports are forbidden.

### 3.5 Module-level constants

Group constants after imports, `SCREAMING_SNAKE_CASE`, with the unit in the name:
`_RECONCILE_INTERVAL_SECONDS`, never `_INTERVAL`. Constants used by tests are
importable directly; a test never duplicates the literal.

## 4. Naming

Naming is the densest API surface a module exposes. A renamed function is a
refactor; a renamed concept is a migration. Choose names assuming you cannot change
them.

### 4.1 Functions are verbs; nouns are reserved for data

A function name starts with a verb; a class or dataclass name is a noun. A function
that returns a derived value uses `build_*`, `compute_*`, or `make_*`. A function
that mutates returns `None` and uses `apply_*`, `record_*`, `upsert_*`.

### 4.2 Predicate prefixes

Boolean returns start with `is_`, `has_`, `should_`, `can_`, or `was_`. The shape
of the answer is visible at the call site without checking the signature.

### 4.3 Forbidden generic names

Forbidden at module or class scope: `data`, `info`, `result`, `value`, `obj`,
`item`, `tmp`, `helper`, `util`, `utils`, `manager`, `handler`, `processor`,
`do_*`. `item` is allowed only as a loop variable over a named iterable
(`for chunk in chunks:` is better still). `result` is allowed only as a local
accumulator immediately followed by a named return.

### 4.4 Domain language wins

When the Paperless API field is `correspondent`, the Python word is `correspondent`,
not `sender`. When the store column is `content_hash`, that is the word everywhere.

| Domain word        | Synonyms forbidden                          |
|--------------------|---------------------------------------------|
| `document`         | doc (in prose/identifiers), file, record    |
| `chunk`            | fragment, segment, piece, passage           |
| `embedding`        | vector (the *list of floats* is a vector; the stored row is an embedding) |
| `correspondent`    | sender, author, party                       |
| `reconciliation`   | sync, refresh, scan                         |
| `query_plan`       | search_spec, intent, parsed_query           |
| `source_document`  | hit, match, result                          |

`doc` is permitted only as a local loop variable bound to a Paperless API document
dict (`for doc in documents:`), mirroring the conventional `conn` for connections.

### 4.5 No abbreviations

`configuration` in prose, `Settings` for the config object (existing convention);
`connection`, not `conn`, except for a `sqlite3.Connection` where `conn` is the
project-wide convention; `request`/`response`, not `req`/`resp`. The permitted
abbreviations are: `conn` (SQLite), `doc` (a Paperless API document dict, loop
variable only), `id` as a primary-key suffix.

### 4.6 Loggers and locks

A module-level structlog logger is named `log` (`log = structlog.get_logger(__name__)`)
— the existing project convention. A module-level `threading.Lock()` is named
`_<resource>_lock`. A cached singleton is `_<resource>` with a `get_<resource>()`
accessor.

## 5. Type System & Data Shapes

Types are the shape contract a function exports to its callers and to the type
checker. A function with imprecise types pushes the burden of correctness onto
every caller.

### 5.1 Public functions are fully typed

Every public function and method annotates every parameter and the return type.
Private helpers are annotated unless they are one-line trivial wrappers. The type
checker passes on `main`.

### 5.2 Frozen dataclasses for I/O shapes

A function that takes or returns structured data uses a frozen dataclass. The
project already does this — `ClassificationResult`, `TaxonomyContext`. New shapes —
`Chunk`, `EmbeddedChunk`, `QueryPlan`, `SearchResult`, `SourceDocument` — follow
suit:

```python
@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: int
    title: str
    correspondent: str | None
    document_type: str | None
    created: str | None
    snippet: str
    paperless_url: str
    score: float
```

`frozen=True` forbids accidental mutation; `slots=True` shaves memory and prevents
attribute typos.

### 5.3 `TypedDict` for external API shapes

The JSON returned by the Paperless-ngx API is described as a `TypedDict` — it pins
field names and types without copying values into a dataclass when no
transformation is needed. The existing `DocumentMetadataUpdate` is the pattern.
`NotRequired` marks fields the upstream may omit. A daemon translates the
`TypedDict` into a domain dataclass at its boundary; downstream code never sees the
raw foreign shape.

### 5.4 `X | None` only for genuine absence

PEP 604 unions (`X | None`, never `Optional[X]`). `None` is reserved for a
meaningful absence — "no row yet", "no correspondent set". A function that returns
`X | None` because a *failure path* wants to bail early is using `None` as a
half-baked exception — raise instead.

### 5.5 `Any` is a code smell

Every `typing.Any` carries a one-line comment immediately above explaining why a
tighter type is impossible. Without the comment, the type checker's strictness is
cosmetic.

### 5.6 Pydantic at the HTTP boundary only

Pydantic models parse and validate HTTP requests and responses in `search/api.py`.
Once validated, the search pipeline, the indexer, and the store work with plain
frozen dataclasses. A Pydantic model in `store/`, `search/core.py`, or `indexer/`
is wrong — its validation cost is paid on every internal call and its schema
couples internals to the wire format.

### 5.7 `from __future__ import annotations`

Mandatory in every new module. Annotations become strings; circular type-only
imports disappear. Type-only imports that would otherwise cycle go under
`if TYPE_CHECKING:`.

### 5.8 No tuple returns of more than two items

`tuple[X, Y]` is a pair (`(value, found)`). Three or more must be a dataclass — a
positional puzzle at the call site is not acceptable.

## 6. Errors

Exceptions are part of the API. They are designed at the same time as the success
path. Unexpected exceptions propagate; expected ones are caught at the layer that
knows the remediation.

### 6.1 Domain exceptions live where they are raised

Each subsystem owns its exception hierarchy in the module that raises it. The store
defines `StoreError` and its subclasses; the search pipeline defines `SearchError`
and, e.g., `PlannerError`. Transport-shaped failures — timeouts, connection errors,
5xx after retries — surface from `PaperlessClient` and the LLM wrapper as their own
error types and are caught as such; they are not re-wrapped into domain errors.

Generic `RuntimeError`, `Exception`, and `ValueError` (outside argument validation)
are not domain errors. Raising one in production code is a bug — the caller cannot
meaningfully handle it.

### 6.2 Exception hierarchy

A subsystem's base inherits from `Exception`, never `BaseException`. Each specific
case is a subclass with a docstring naming the failure. Subclasses are
domain-shaped, not HTTP-status-shaped.

### 6.3 `raise X from original` is mandatory

When converting one exception to another, always `raise NewError(...) from original`
(or `from None` when the original carries a secret — [§10](#10-security)). The
traceback is forensic evidence; severing it is destruction of evidence.

### 6.4 `except Exception:` is reserved for outer boundaries

The only legitimate uses of bare `except Exception:` are:

1. The polling loop in `common/daemon_loop.py` — a single bad document must not
   crash the daemon. (Already implemented there.)
2. The per-document worker dispatch inside the thread pool — one document's failure
   is logged and isolated, the batch continues.
3. The FastAPI exception handler in `search/api.py` — turning anything missed into
   a 500.
4. The MCP request handler — a tool call failure becomes a structured error, not a
   server crash.

Every such site has a `# rationale:` comment and, inside the handler, logs with
`log.exception(...)` (full traceback) and either re-raises, returns a fallback, or
records the failure. A `try/except` whose `except` body is only `pass` is forbidden.

### 6.5 Distinguish expected from unexpected

For every `except` clause: *did I expect this could happen?* If yes, you have a
plan — log, fall back, retry, surface a user-facing error. If no, the exception
propagates untouched. There is no third option.

### 6.6 Errors carry context, never secrets

An exception message includes the inputs that produced it — `document_id`, the
model name, the HTTP status — and never the Paperless token, the API key, or the
document's content body.

## 7. Logging & Observability

The project uses **structlog**, configured once in `common/logging_config.py` for
JSON or console output. Logs are the only window the operator has into a process
they cannot attach a debugger to.

### 7.1 One logger per module

```python
import structlog
log = structlog.get_logger(__name__)
```

`__name__` produces `indexer.reconciler`, `search.planner`, and so on, so the
operator can raise the level for one noisy area. The logger is named `log` — the
existing project convention. `print()` in `src/` is a CI lint failure; the only
carve-out is a pre-logging fatal-config-error path in a daemon entry point.

### 7.2 Stable event string, structured context

The first argument to a log call is a **stable string** describing the event. Every
variable goes in a keyword argument — never interpolated into the message.

```python
# Good — greppable, machine-parsable.
log.info("document.indexed", document_id=document_id, chunk_count=len(chunks))

# Bad — every call is a different string.
log.info(f"Indexed document {document_id} with {len(chunks)} chunks")
```

New code prefers short dotted event names (`reconcile.pruned`, `search.refined`,
`embedding.batch_failed`). They make queries portable across the console and JSON
sinks and across tests-on-logs.

### 7.3 Levels

- **`DEBUG`** — for the developer running locally. Payload shapes, branch taken,
  cache hit/miss. Off in production.
- **`INFO`** — steady-state domain events. Reconciliation started, N documents
  indexed, a search served, a daemon entered its idle wait.
- **`WARNING`** — recoverable anomaly. A retryable HTTP 502, an embedding-model
  mismatch triggering a rebuild, a document skipped for empty content.
- **`ERROR`** — an operation failed; logged with `log.exception(...)` so the
  traceback is attached.
- **`CRITICAL`** — process integrity at risk. Store unwritable, preflight failed.

A `WARNING` that fires every steady-state cycle is either a real warning (fix the
root cause) or wrongly classified (lower it).

### 7.4 Never log secrets

Forbidden as log values or substrings: the Paperless API token, the OpenAI API key,
the `SEARCH_API_KEY`, and full document content bodies. Document *titles* and
*metadata* are not secrets in this project's threat model — the operator owns the
archive — and may be logged for triage. When forensic correlation needs a token,
log a length-bounded irreversible prefix, never the whole value.

### 7.5 `log.exception` inside an `except`

Inside an `except` block, `log.exception("event.name", ...)` attaches the active
traceback. Plain `log.error(str(exc))` discards the stack — never do that in an
`except`.

### 7.6 Observability surfaces

- `GET /api/healthz` on the search server — store reachable, schema version
  current. The Docker healthcheck.
- `GET /api/stats` — index size, last reconciliation time.
- Daemon logs to stdout — the operator reads them via `docker logs`.

A new operational concern adds a `/api/healthz` field or a structured log event,
never an out-of-band metric file.

## 8. Concurrency & I/O

Each daemon runs a polling loop that fans documents across a `ThreadPoolExecutor`.
The search server runs FastAPI's thread pool. State that crosses a thread is shared
state and is guarded.

### 8.1 Outbound I/O goes through the shared clients

- **Paperless-ngx HTTP** — only through `PaperlessClient` (`common/paperless.py`).
  It owns retries, the timeout budget, the auth header, and pagination. A bare
  `httpx` call against Paperless outside that module is the blocker.
- **LLM calls** — only through the `common/llm` wrapper, which owns the OpenAI SDK
  singleton, the model-fallback chain, and retry/stats.
- **Embeddings** — only through `common/embeddings.py`, which owns request
  batching and retry.

A bespoke client gets the timeout, the retry, or the auth header wrong eventually;
the shared ones get it right by construction.

### 8.2 SQLite only through `store/`

Every `sqlite3.connect`, every cursor, every SQL string lives in `src/store/`. A
`sqlite3` import anywhere else is a review-blocker — it bypasses the WAL
configuration, the pragmas, the foreign-keys setting, and the schema-version check.
See [§9](#9-the-store).

### 8.3 The `PaperlessClient` is not thread-safe

Each worker thread constructs its own `PaperlessClient` (its own `httpx` session) —
the existing daemons already do this. The OpenAI SDK client is a thread-safe
singleton, initialised once and shared. Do not share a `PaperlessClient` across
threads.

### 8.4 The store has exactly one writer; reads are concurrent

The SQLite store runs in WAL mode: one writer, many concurrent readers. The
**indexer is the sole writer process** and enforces it — it takes an exclusive
`flock` on startup, so a second indexer fails fast and loud. Within the indexer,
document embedding runs in parallel across worker threads, but the write
transaction is serialised — the `StoreWriter` holds an internal `threading.Lock`
around each transaction. The search server reaches the store only through
`StoreReader`, whose API exposes no write methods. A connection-level `mode=ro` is
deliberately **not** used: a read-only SQLite connection cannot maintain the WAL
`-shm` coordination file while a separate writer process is live. Read-only is
guaranteed by the `StoreReader` API surface plus the single-writer `flock`, not by
the connection string.

### 8.5 Module-level mutable state is forbidden by default

A module-level `dict` or `list` mutated at runtime is a global. The only legitimate
uses are a documented cache with a TTL or max size, or a documented singleton that
owns a `threading.Lock` and a one-line comment explaining why a global is required.
Everything else goes through the store or is passed as an argument.

### 8.6 Threads and pools are named

Every `ThreadPoolExecutor` is constructed with `thread_name_prefix=`. Unnamed
threads make profilers and log correlation meaningless.

### 8.7 Timeouts everywhere

Every outbound call has a timeout. The shared clients enforce defaults; tests must
not mock around them.

### 8.8 Graceful shutdown

The daemons honour SIGTERM/SIGINT via `common/shutdown.py` — a thread-safe flag
checked before each poll. A new long-running operation checks the flag at safe
points and leaves the store consistent if interrupted; the per-document upsert
transaction ([§9.6](#96-transactions-are-explicit)) guarantees a clean boundary.

## 9. The Store

The store is a single SQLite file (`INDEX_DB_PATH`) holding the search index:
document metadata, text chunks, vector embeddings (`sqlite-vec`), and a full-text
index (FTS5). It is the only database in the project.

### 9.1 The store owns all SQL

`src/store/` is the only package that imports `sqlite3` or `sqlite-vec` and the
only place SQL strings exist. The indexer and the search pipeline call
`StoreWriter` and `StoreReader` methods; they never see a cursor or a row. A
repository method does **one** logical operation — composing several into a
workflow is the caller's job, not the store's.

### 9.2 Schema is declared, applied idempotently, and versioned

The schema lives in `store/schema.py` as literal `CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS` / virtual-table statements. There is no ORM. Reading
the schema file tells you, authoritatively, what shapes exist.

Unlike a pure DDL-as-code project, the store **has a migration mechanism**, because
the index is a long-lived artifact the operator cannot be asked to rebuild by hand
on every upgrade. `store/migrations.py` holds an ordered list of migration
functions keyed to `meta.schema_version`; `ensure_schema()` applies the pending
ones inside a transaction on startup. v1 is "create the schema"; the mechanism
exists from the first commit so a reliable, evolving product never needs a manual
wipe.

### 9.3 Repository methods return dataclasses, never raw rows

`sqlite3.Row` is convenient and leaky. A public `StoreReader` / `StoreWriter` method
returns a frozen dataclass (or a list of them), never a `sqlite3.Row` and never a
bare `dict`. Private helpers within `store/` may pass rows between themselves; the
raw row must not cross the package boundary.

### 9.4 No raw-row coupling for vectors and FTS

`sqlite-vec` and FTS5 virtual tables are an implementation detail of `store/`. The
`StoreReader` exposes `vector_search`, `keyword_search`, and `get_documents` —
typed, dataclass-returning methods. No caller knows the name of the `vec0` table or
writes a `MATCH` clause.

### 9.5 Parameter-substitute, always

```python
# Good
conn.execute("SELECT id FROM documents WHERE content_hash = ?", (content_hash,))

# Catastrophic — string-built SQL is a security incident.
conn.execute(f"SELECT id FROM documents WHERE content_hash = '{content_hash}'")
```

Even an "obviously safe" integer uses a parameter. The one sanctioned dynamic-SQL
pattern is the `IN ({placeholders})` batch query, where `placeholders` is built
only from `?` characters (`",".join("?" * n)`) and carries a `# rationale:` comment
— no value is ever interpolated, only the count of placeholders.

### 9.6 Transactions are explicit

A multi-statement store operation runs inside an explicit `with conn:` block. The
per-document upsert — delete the document's old chunks from `chunks`, `chunks_vec`,
and `chunks_fts`; insert the new chunks; update the `documents` row — is **one
transaction**. A crash mid-document leaves the previous version fully intact; there
is never a half-indexed document.

### 9.7 Crash safety pragmas

WAL mode, `synchronous = NORMAL`, and `foreign_keys = ON` are set centrally when
the store opens a connection. A new pragma is added there with a one-line comment
naming the trade-off, never per-call.

### 9.8 Foreign keys cascade; virtual tables do not

`chunks` declares `ON DELETE CASCADE` to `documents`. The `sqlite-vec` and FTS5
virtual tables do **not** honour FK cascade — `StoreWriter` deletes from them
explicitly within the same transaction. This is the kind of non-obvious invariant
that gets a `# why` comment at the delete site.

## 10. Security

The OCR and classifier daemons are headless and unexposed. The **search server and
MCP server are network-facing** — a threat surface the original daemons never had.
Every change to a search endpoint, a tool, or the answer prompt is a security
change.

### 10.1 API authentication — fail closed

The search API and MCP server require `SEARCH_API_KEY`. It is **mandatory**: an
unset or empty key is a fatal preflight error — the search and MCP servers refuse
to start, with a `CRITICAL` log line. They never run in an unauthenticated state.
The index holds the operator's personal documents; a search surface that is open
"by default" is a data breach one misconfiguration away. When the key is set, every
`/api/*` request and every MCP call requires a matching bearer token. A new
endpoint is gated by the same check; opting one out requires a written
justification. Network restriction — a reverse-proxy IP allowlist, a VPN — is
defence in depth on top of the key ([§1.11](#111-fail-closed-fail-loud)), never a
substitute for it.

### 10.2 Prompt injection is a real attack class

Retrieved document chunks are **untrusted input** — a document can contain text
that reads as an instruction ("ignore your previous instructions and …"). Every
prompt that embeds retrieved content places it below an explicit delimiter and
instructs the model to treat everything below as data, never as instructions —
reusing the pattern already in the OCR transcription prompt. A new prompt that
interpolates document content without that guard is a security finding.

### 10.3 Secrets live in the environment

The Paperless token, the OpenAI key, and the `SEARCH_API_KEY` are supplied via
environment variables, loaded once into `Settings`, and never written to disk,
never logged ([§7.4](#74-never-log-secrets)), never returned in an API response or
an error body.

### 10.4 Validate at the boundary, once

HTTP request bodies are validated by Pydantic in `search/api.py` — the 4xx is
produced there, once. The query string has a documented maximum length. Inner
pipeline functions trust the validated shape. The MCP server validates tool
arguments at its boundary the same way.

### 10.5 The search server reads the store read-only

The search server reaches the store only through `StoreReader`, which exposes no
write methods, and the indexer holds an exclusive `flock` as the sole writer. A bug
in the read side cannot corrupt the index — the read API has no write surface to
misuse. This is a structural control, not a convention.

### 10.6 Abuse protection on exposed endpoints

A search costs real LLM money. The search server enforces a bounded global
concurrency limit on `/api/search` (reusing the `common/concurrency` semaphore
pattern) so an exposed endpoint cannot be turned into a billing-denial attack. The
hard ceiling of three LLM calls per query ([§14.3](#143-the-search-pipeline-has-a-hard-llm-budget))
bounds the per-request cost.

### 10.7 No `eval`, no `exec`, no unsafe deserialisation

JSON and manually-written dataclass parsing cover every need. `eval` and `exec` are
forbidden in `src/`. Unsafe deserialisation of data that crossed a trust boundary —
any format that can execute code on load — is forbidden; external input is parsed
as JSON only.

### 10.8 Outbound destinations are known

The daemons and the search side talk to exactly three kinds of host: the configured
Paperless-ngx instance, the configured LLM provider (OpenAI or a configured Ollama
URL), and nothing else. A new outbound destination is justified in the PR that
introduces it.

## 11. Testing

Tests are the executable specification of the system. A change with no test is a
change with no documented expectation.

### 11.1 The pyramid

- **Unit tests** dominate. Milliseconds, no network, no real filesystem outside
  `tmp_path`, one cohesive unit each.
- **Integration tests** cover module boundaries — the indexer worker against a mock
  Paperless and a real temporary store; the search pipeline end to end against a
  mock LLM and a populated temporary store.
- **End-to-end tests** exercise a full workflow against mocks. No test hits a live
  Paperless, OpenAI, or Ollama.

The existing `unit` / `integration` / `e2e` pytest markers are the mechanism. New
markers need a written justification.

### 11.2 One test file per source file

`src/indexer/chunker.py` ↔ `tests/unit/indexer/test_chunker.py`. The mirroring is
mechanical; a moved function moves its test in the same PR.

### 11.3 Tests are named for behaviour

```python
def test_reconciler_prunes_documents_deleted_from_paperless() -> None: ...
def test_chunker_carries_overlap_between_adjacent_chunks() -> None: ...
def test_search_returns_no_matches_without_calling_the_llm() -> None: ...
```

A name containing a function name (`test_run_2`) is a smell — it couples the test
to *how*, not *what*.

### 11.4 Determinism: mock the LLM, the embeddings, and Paperless

The agentic pipeline is testable offline precisely because every stage takes its
LLM client and store reader by injection. A planner test feeds a mock LLM a canned
`QueryPlan`; a synthesiser test feeds a canned answer. Embedding calls are mocked at
the `common/embeddings` boundary. Paperless is mocked with the existing
`tests/helpers/mocks.py` builders. A test that depends on wall-clock time, RNG, or
dict ordering is flaky waiting to happen — inject the clock, seed the RNG, sort the
iteration.

### 11.5 Factories over hand-built objects

`tests/helpers/factories.py` grows `make_chunk`, `make_query_plan`,
`make_source_document` alongside the existing `make_document` and
`make_classification_result`. A test instantiates a dataclass through a factory that
fills irrelevant fields with deterministic defaults, so the one field that matters
is visible.

### 11.6 More than five mocks means the wrong layer

A test that needs six mocks for one assertion is testing wiring, not behaviour.
Push the test down a layer or up a layer.

### 11.7 No `time.sleep` in tests

Replace with an injected clock or a condition-based bounded wait. A sleep is flaky
on a slow CI runner.

### 11.8 Frontend tests

Frontend testing lives under [§12.8](#128-every-library-component-is-tested-and-catalogued)
— Vitest plus React Testing Library, one test file per component, behaviour names,
the same pyramid.

## 12. Frontend Architecture

`web/` is a React + Vite + TypeScript single-page application. It exists to query
the search index and is built to grow into a multi-page product. Its non-negotiable
goal is **zero design drift**: every page is assembled from the same reviewed
components, and there is exactly one source of design values.

### 12.1 Stack

| Concern          | Choice                          | Note |
|------------------|---------------------------------|------|
| Build            | Vite                            | Fast dev server, static build |
| Language         | TypeScript, `strict` mode       | No `any` without a `// rationale:` |
| UI               | React 18                        | Function components and hooks only |
| Routing          | React Router                    | Multi-page from day one |
| Server state     | TanStack Query                  | All API state; no hand-rolled fetch state |
| Styling          | CSS Modules + design tokens     | Not Tailwind, not CSS-in-JS |
| Catalogue        | Storybook                       | Every library component has a story |
| Test             | Vitest + React Testing Library  | Mirrors the backend's discipline |
| Quality gates    | ESLint, Prettier, Stylelint     | Boundary lint + no-hardcoded-values lint |

A new frontend dependency is justified like any other ([§15](#15-dependencies)).

### 12.2 Directory layout

```
web/src/
├── styles/
│   ├── tokens.css      design tokens — the single source of design values
│   ├── themes.css      light/dark token overrides
│   └── global.css      resets, @font-face, base element styles
├── components/         the component LIBRARY — generic, app-agnostic
│   ├── primitives/     Button, IconButton, Input, Link, Badge, Chip, Card,
│   │                   Icon, Spinner, Skeleton, Tooltip
│   ├── layout/         Page, Container, Section, Stack, Grid, Divider, NavBar
│   └── patterns/       SearchField, Select, FilterPanel, Modal, Toast, Tabs,
│                       EmptyState
├── features/           DOMAIN components — know about search/documents
│   ├── search/         SearchBar, FilterControls, AnswerCard, SourceCard,
│   │                   SourceList, QueryPlanSummary, CitationLink
│   └── document/       DocumentMeta, DocumentSnippet
├── pages/              ROUTES — compose features + layout only
│   └── SearchPage.tsx
├── api/                client.ts, types.ts, hooks.ts — the typed API layer
├── hooks/              generic reusable hooks (useDebounce, useTheme)
├── routes.tsx          the route table
├── App.tsx
└── main.tsx
```

### 12.3 The layer stack and its one rule

There are five layers. **Dependencies flow strictly downward; nothing imports
upward or sideways across a boundary.** This is enforced mechanically by
`eslint-plugin-boundaries` — a violating import fails CI, it is not a review
judgement call.

```
   pages/        may import:  features/, components/layout/, api/, hooks/
      │
      ▼
   features/     may import:  components/*, api/, hooks/
      │
      ▼
   components/   may import:  lower components/, styles/
      │
      ▼
   styles/       imports nothing
```

What this rule buys, concretely:

- A `pages/` file **never writes a colour, a `<button>`, or a CSS rule.** It
  composes `features` and `layout`. If a page needs something visual that does not
  exist, the something is added to the library — reviewed once, then reusable
  everywhere. A page cannot solve a visual problem locally. That is the structural
  guarantee against the "slightly different button on every page" failure.
- `features/` is the only layer that knows the words "search" and "document".
- `components/` is generic and app-agnostic — a `Card` knows nothing about source
  documents.
- Adding a new page is one route entry plus composition. It cannot introduce
  styling.

`api/` and `hooks/` are cross-cutting leaves: `api/` is imported by `features` and
`pages`; `hooks/` holds generic hooks importable by `components`, `features`, and
`pages`. Neither imports a component.

### 12.4 Design tokens are the only source of design values

`styles/tokens.css` encodes the project's design system — adopted from the Apple
design language documented in the repo-root `DESIGN.md` — as CSS custom properties:
colours, the SF Pro type scale, the 8px-based spacing scale, the radius ladder, the
single card shadow, breakpoints.

**No component contains a hardcoded design value.** A hex colour, a raw `px` size,
a font stack, a shadow literal anywhere outside `tokens.css` is a Stylelint failure.
A primitive that needs the accent colour writes `var(--colour-accent)`. Change a
token, and every component updates — that is the point.

Token identifiers use British spelling: `--colour-accent`, `--colour-bg-alt`, never
`--color-*`.

### 12.5 Only `components/` carries styling

CSS Modules live beside their component (`Button.tsx` ↔ `Button.module.css`). A CSS
Module exists only in `components/`. `features/` and `pages/` compose styled
components; they do not ship `.module.css` files. A feature that "just needs a bit
of CSS" needs a library component instead.

### 12.6 The typed API layer

`web/src/api/` is the only place the frontend talks to the backend:

- `client.ts` — a typed `fetch` wrapper owning the base URL, the `SEARCH_API_KEY`
  header, and error normalisation.
- `types.ts` — TypeScript types mirroring the FastAPI Pydantic schema
  (`SearchResult`, `SourceDocument`, `QueryPlan`, facets). Frontend and backend
  shapes are kept in deliberate correspondence; a divergence is a bug.
- `hooks.ts` — TanStack Query hooks (`useSearch`, `useFacets`, `useStats`).

A component or page that calls `fetch` directly bypasses the auth header, the error
handling, and the types. It is a review-blocker.

### 12.7 Component standards

Every library component:

- Is a typed-props function component. Props are an exported `interface`; no
  `React.FC`; no `any`.
- Renders accessible markup — semantic elements, ARIA where needed, full keyboard
  operation, and the `2px` accent-colour focus ring the design system specifies.
- Reads design values only from tokens ([§12.4](#124-design-tokens-are-the-only-source-of-design-values)).
- Is responsive per the documented breakpoints.
- Has a Storybook story and a Vitest test ([§12.8](#128-every-library-component-is-tested-and-catalogued)).

### 12.8 Every library component is tested and catalogued

- **A Storybook story per component.** The catalogue is the canonical, visible
  inventory of what exists — the working defence against re-inventing a component
  that already exists.
- **A Vitest + React Testing Library test per component**, mirroring the file tree
  (`Button.tsx` ↔ `Button.test.tsx`), named for behaviour, asserting what the user
  sees and does — not implementation detail.

### 12.9 State

Server state — search results, facets, index stats — is owned by TanStack Query;
the frontend never hand-rolls loading/error/cache state. Local UI state uses React
state and, where genuinely shared (theme, an open filter panel), a small Context.
Redux or an equivalent global store is unjustified at this size; adding one needs a
written justification.

### 12.10 Build and CI

The Vite build runs in a Node stage of the existing multi-stage Dockerfile; the
static output is copied into the final image and served by the search server at
`/`, same-origin. The frontend CI lane runs, in order: `tsc` typecheck, ESLint
(including the boundary rules), Stylelint, Vitest, and `vite build`. A red lane
blocks merge exactly as a backend gate does.

## 13. Documentation

Documentation has three audiences: operators read `README.md`, architects read
`DESIGN.md` and `docs/`, implementers read source, docstrings, and this file. Do
not conflate them.

### 13.1 Public docstrings

Every public function, class, and module has a docstring: a one-line summary, then
— only when they add information — `Args:` / `Returns:` / `Raises:` sections. A
docstring explains *what* and *why*; the signature already shows the types.

### 13.2 Package `__init__.py` carries a paragraph

A package's `__init__.py` opens with a paragraph naming what the package is for,
what it depends on, and what it forbids — the entry point for someone reading the
tree for the first time. Import-time side effects in `__init__.py` are forbidden;
startup belongs in `common/bootstrap.py`.

### 13.3 Comments answer "why"

A comment names the invariant, the upstream quirk, or the constraint — never
paraphrases the next line. The existing `AGENTS.md` and `docs/` describe the OCR and
classification pipelines; the indexer, store, and search subsystems get equivalent
`docs/` pages in the PRs that build them.

### 13.4 The canonical documents

`README.md` — running the project. `DESIGN.md` — the visual design system and the
architecture rationale. `AGENTS.md` — the codebase guide for AI agents.
`CODE_GUIDELINES.md` (this file) — how we agree to write code. `docs/` — per-pipeline
deep dives. A new top-level markdown file needs a written justification.

### 13.5 `TODO` / `FIXME` / `HACK`

`# TODO:` and `# FIXME:` carry an owner and a tracking reference — a bare one is
forbidden. `# HACK:` carries a removal trigger ("remove once sqlite-vec ships
filtered KNN"). A `TODO` with no movement in six months is either done, deleted, or
rewritten as a permanent design note.

### 13.6 ASCII diagrams over external assets

A diagram that fits in 80 columns lives in the source or the markdown as ASCII art,
the way the taxonomy diagram in [§2](#2-module-taxonomy) does.

## 14. Performance

The project's hot paths are reconciliation (indexer) and query latency (search).
Neither is CPU-bound. Performance work without a measurement is speculative;
performance work that complicates a call site without a number is harmful.

### 14.1 Don't optimise without a measurement

A change claiming "faster" includes a number — a `timeit`, a latency figure. "I
think this is faster" is rejected.

### 14.2 Embeddings are batched; brute-force vector search is fine at this scale

The embedding client sends a document's chunks as one batched request, splitting
into API-sized batches internally. The store does **exact brute-force KNN** — at the
project's target of roughly 1,000–10,000 documents (tens of thousands of chunks)
this runs in single-digit milliseconds and needs no approximate-nearest-neighbour
index. An ANN index is added only if and when a measurement against a real corpus
shows brute-force has become the bottleneck — not before.

### 14.3 The search pipeline has a hard LLM budget

The agentic pipeline plans once, retrieves, and refines **at most once**:
`SEARCH_MAX_REFINEMENTS` defaults to 1. The guaranteed ceiling is **three LLM calls
per query**. This bound is a correctness and cost property, not a tuning knob —
raising it past a small constant requires a written justification and is a security
review point ([§10.6](#106-abuse-protection-on-exposed-endpoints)).

### 14.4 Re-index only what changed

Reconciliation re-embeds a document only when its content hash changes. A metadata-only
change (the classifier set a title or tags) updates the `documents` row without
re-chunking or re-embedding. Paying for embeddings on an unchanged document is a bug.

### 14.5 Caches need a bound

Every in-process cache declares a TTL, a max size, or a documented rebuild trigger.
The taxonomy/facet maps are rebuilt once per reconciliation cycle, not per document.
An unbounded cache is a memory leak.

### 14.6 Don't pre-allocate for hypothetical scale

The project targets a personal-to-large document archive. "What if there are ten
million documents" is not a scale served today. The simple version ships; the day a
real corpus is measured as slow, the optimisation is made against that measurement.

## 15. Dependencies

Every runtime dependency is a permanent commitment to track its advisories and
absorb its breaking changes. Treat new dependencies as expensive.

### 15.1 The dependency set is deliberate

Backend runtime dependencies, current and planned: `httpx`, `openai`, `Pillow`,
`pdf2image`, `structlog` (existing); `sqlite-vec`, `fastapi`, `uvicorn`, `mcp`
(added by the search subsystem). The project deliberately does **not** take
`tiktoken` (char-based chunking suffices) or a cross-encoder re-ranker / `torch`
(hybrid RRF suffices). Frontend dependencies are listed in `web/package.json`.

### 15.2 A new dependency needs a written justification

A PR adding a runtime dependency states, in the description: what it does, what was
considered first (standard library, then an existing dependency, then custom code),
who maintains it, and how much of its surface the project actually uses. A
dependency that wins a single utility function is usually inlined as a small tested
helper instead.

### 15.3 Pin deliberately

Python dependencies pin with the compatible-release operator (`~=`); major versions
are bumped deliberately, not automatically. Frontend dependencies are pinned in
`package.json` with a committed lockfile.

### 15.4 Optional providers stay optional

The project supports both OpenAI and Ollama. Provider-specific behaviour stays
behind the `LLM_PROVIDER` setting and the shared `common/llm` and
`common/embeddings` wrappers; the rest of the codebase is provider-agnostic.

### 15.5 No runtime dependency installation

`pip install` at runtime is forbidden. A feature that needs a package adds it to
`pyproject.toml` and ships it in the container.

## 16. Workflow

The workflow is the contract between contributors. It is short on purpose.

### 16.1 Conventional Commits

Commit messages follow the Conventional Commits format — the project's existing
history already does:

```
<type>(<optional scope>): <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `perf`, `style`, `test`, `docs`, `build`, `ops`,
`chore`. The description is imperative, present tense, lower-case, no trailing
period (`feat(indexer): add content-hash change detection`). A breaking change adds
`!` before the colon and a `BREAKING CHANGE:` footer.

Commit messages contain **no AI attribution** — no "Co-Authored-By" for an AI tool,
no "generated by" line. British English, here as everywhere.

### 16.2 Each commit builds and tests on its own

Every commit on `main` is green. WIP that interleaves broken and fixed states is
squashed before merge. A stack of small green commits is the goal.

### 16.3 Branch naming

`<type>/<short-description>` using the Conventional Commit types —
`feat/indexer-reconciler`, `fix/store-cascade-delete`, `refactor/search-core`. The
description is kebab-case and descriptive.

### 16.4 PR description: what / why / tested

Every PR opens with three sections — **What** (the change), **Why** (the reason; a
bug fix names the bug, a feature names the need), **Tested** (which tests cover it,
what verification was done). A description that only lists changed files is
rejected; the diff already shows *what*.

### 16.5 CI gates are not optional

| Gate            | Scope     | Failure means                          |
|-----------------|-----------|----------------------------------------|
| Tests           | backend   | Behaviour regression                   |
| Lint + format   | backend   | Style violation                        |
| Types           | backend   | Type-contract violation                |
| Tests           | frontend  | Behaviour regression                   |
| Typecheck       | frontend  | TypeScript error                       |
| Lint            | frontend  | ESLint / boundary / Stylelint violation|
| Build           | frontend  | `vite build` fails                     |
| Docker build    | image     | Image will not build reproducibly      |

A red gate blocks merge. "Re-run until green" is forbidden — flakiness is a defect;
file it and fix the test.

### 16.6 Reviews apply this document

A reviewer's job is to apply the rules here, not to admire the diff. A reviewer who
spots a violation requests a change; a reviewer who approves a violation has broken
the contract. A PR touching the search or MCP server — the network-facing surface —
gets a review with the security section ([§10](#10-security)) explicitly in mind.

### 16.7 Don't push or open PRs unprompted

Commits land locally; pushing to a remote and opening a PR happen only when the
maintainer asks. Never amend or force-push a commit that has been pushed or
reviewed.

## 17. Deletion Checklist

A merge-time checklist. Every box is the *removal* of something that pretends to be
useful. Run it against every PR before approving.

### 17.1 Dead and commented-out code

- [ ] No `if False:` blocks, no unreachable paths after `raise`/`return`.
- [ ] No code commented out "in case we need it later" — git remembers.

### 17.2 Defensive guards on impossible conditions

- [ ] No `if x is None: return None` after a function whose return type excludes
      `None`.
- [ ] No `assert isinstance(...)` at the top of a function with a typed signature.

### 17.3 Wrappers that just call a library

- [ ] No `def get_now(): return datetime.now(UTC)`-style wrappers. A wrapper earns
      its name only by adding behaviour — validation, retry, a domain default.

### 17.4 Speculative generality

- [ ] No parameter that no caller supplies.
- [ ] No base class, protocol, or ABC with a single implementation.

### 17.5 Files and functions over the ceiling

- [ ] No source file over 500 lines, no function over 60 body lines, without a
      `# rationale:` / `// rationale:` ([§3.1](#31-hard-limits)).

### 17.6 Bare `except` and swallowed errors

- [ ] Every `except Exception:` is at one of the four documented sites
      ([§6.4](#64-except-exception-is-reserved-for-outer-boundaries)), with a
      `# rationale:`, and logs with `log.exception(...)`.
- [ ] No `except SomeError: pass`.

### 17.7 SQL and database

- [ ] No `sqlite3` import outside `src/store/`.
- [ ] No value interpolated into a SQL string — parameters only
      ([§9.5](#95-parameter-substitute-always)).

### 17.8 I/O through the shared clients

- [ ] No bare `httpx` call against Paperless outside `common/paperless.py`.
- [ ] No direct `openai` call outside `common/llm` and `common/embeddings`.

### 17.9 Logging

- [ ] No secret — Paperless token, API key — in a log line
      ([§7.4](#74-never-log-secrets)).
- [ ] No `print()` in `src/`. No f-string interpolated into a log event
      ([§7.2](#72-stable-event-string-structured-context)).

### 17.10 Naming

- [ ] No `data`, `info`, `result`, `tmp`, `helper`, `util` at module or class
      scope ([§4.3](#43-forbidden-generic-names)).
- [ ] American spelling in any identifier, comment, or string is corrected to
      British.

### 17.11 Types

- [ ] Every `typing.Any` / TypeScript `any` carries a `# rationale:` /
      `// rationale:` comment.
- [ ] Every new public function is fully typed.

### 17.12 Frontend

- [ ] No hardcoded colour, size, radius, or shadow outside `web/src/styles/tokens.css`
      ([§12.4](#124-design-tokens-are-the-only-source-of-design-values)).
- [ ] No `.module.css` outside `components/`.
- [ ] No layer-boundary violation — a `pages/` import of a primitive, a `fetch`
      call outside `api/` ([§12.3](#123-the-layer-stack-and-its-one-rule),
      [§12.6](#126-the-typed-api-layer)).
- [ ] Every new library component ships a story and a test.

### 17.13 Tests

- [ ] One test file per source file; behaviour-named tests.
- [ ] No `time.sleep` in a test; no test with more than five mocks.

### 17.14 Dependencies and config

- [ ] A new dependency carries a written justification
      ([§15.2](#152-a-new-dependency-needs-a-written-justification)).
- [ ] Every new environment variable is documented in `README.md` with name, type,
      default, and purpose.
