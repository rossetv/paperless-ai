# Resilience & Error Handling

The pipeline is built to survive the things that actually go wrong: a flaky
network, a rate-limited API, a model that refuses, a crashed daemon, a
misconfigured tag. This document covers each defence and where it lives.

The guiding rule is **fail closed, fail loud** (`CODE_GUIDELINES.md` §1.11): a
refused operation can be retried, but a silent corruption cannot be undone, so
the system would rather stop than carry on wrong.

---

## Retry with exponential backoff and jitter

Every outbound call goes through one of three shared clients, and each retries
transient failures using the `@retry` decorator (`src/common/retry.py`):

- Paperless HTTP — `PaperlessClient` (`src/common/paperless.py`)
- LLM chat — the `common/llm` wrapper
- Embeddings — `EmbeddingClient` (`src/common/embeddings.py`)

The backoff for attempt *n* (1-based) is:

```
delay = min(2**n × uniform(0.8, 1.2), MAX_RETRY_BACKOFF_SECONDS)
```

With the defaults (`MAX_RETRIES=3`, `MAX_RETRY_BACKOFF_SECONDS=30`) a call is
attempted up to **3 times** — two retries — with sleeps of roughly 2s then 4s
before the final attempt. Raise `MAX_RETRIES` for more persistence; the cap
keeps any single sleep bounded once `2**n` exceeds it.

The jitter factor (0.8–1.2) de-synchronises retries so multiple daemon instances
do not retry in lockstep (the thundering-herd problem).

**4xx errors are never retried.** The Paperless client only raises — and so only
retries — on server errors (5xx); a 4xx response is returned as-is for the caller
to handle, because a bad request or auth failure will not fix itself. The LLM and
embedding clients retry only the connection/timeout/rate-limit/server-error set
below; a `BadRequestError` or `AuthenticationError` propagates immediately.

### Retried error types

| Error | Source | Retried by |
|:---|:---|:---|
| `httpx.RequestError` | Network connectivity failure | Paperless client |
| `httpx.HTTPStatusError` (5xx only) | Paperless server error | Paperless client |
| `openai.APIConnectionError` | LLM/embedding connectivity | LLM + embedding clients |
| `openai.APITimeoutError` | LLM/embedding timeout | LLM + embedding clients |
| `openai.RateLimitError` | Rate limiting | LLM + embedding clients |
| `openai.InternalServerError` | LLM/embedding server error | LLM + embedding clients |

After the final attempt fails the exception is logged with its traceback and
re-raised, so the failure is never swallowed.

---

## Model fallback chains

OCR uses the `OCR_MODELS` chain; classification uses the `CLASSIFY_MODELS` chain.
Each is tried **in order**, falling to the next when the current model:

- **refuses** (OCR only — the response matches an `OCR_REFUSAL_MARKERS` phrase), or
- **returns unusable output** (classification only — unparseable JSON), or
- **errors** after exhausting its retries (rate limit, server error, timeout).

The first model to produce a usable result wins. If every model fails, OCR writes
the fixed refusal marker into the document content and the classifier returns no
result — in both cases the document is quarantined (see below).

Default chains (provider-dependent, same for both stages unless overridden):

- **OpenAI:** `gpt-5.4-mini` → `gpt-5.4` → `gpt-5.5`
- **Ollama:** `gemma3:27b` → `gemma3:12b`

Each provider tracks per-request statistics — `attempts`, `refusals` /
`invalid_json`, `api_errors`, `fallback_successes` — and logs them after each
document for observability.

**Source:** `src/ocr/provider.py`, `src/classifier/provider.py`

> **Aside — adaptive parameter compatibility.** The shared LLM wrapper
> (`src/common/llm.py`) also recovers from a model that rejects an optional
> parameter (`temperature`, `reasoning_effort`, a `json_schema` response format,
> `max_tokens`). On a 400 naming the offending parameter it strips that one
> parameter, retries, and caches the discovery per model — so the next call to
> that model omits it from the start rather than failing again.

---

## Per-document fault isolation

A single document failure **never crashes a daemon**. Two layers guarantee it:

1. **The worker-dispatch boundary** in `src/common/daemon_loop.py` catches every
   exception raised while processing one document, logs it with full context
   (document ID, traceback), and lets the rest of the batch complete.
2. **The polling loop** catches transient Paperless errors around the whole poll,
   logs a warning, and sleeps before retrying — a Paperless outage pauses the
   daemon, it does not kill it.

When a document fails **permanently** — the model could not produce output, or
Paperless rejected the write-back with a 4xx — it is *quarantined*:

1. `ERROR_TAG_ID` is applied (if configured).
2. All pipeline tags are removed, so it leaves the queue instead of looping.
3. User-assigned tags are preserved.
4. The processing-lock tag is released (in a `finally` block).
5. The daemon moves on.

The processor reports the outcome (`SAVED` / `QUARANTINED`, via
`WriteBackOutcome` in `src/common/per_document.py`) so the circuit breaker can
act on a run of failures.

---

## The write-back circuit breaker

A tag daemon spends LLM tokens on a document *before* it writes the result back
to Paperless. If every write-back is being rejected the same way — a deleted
tag, a misconfigured custom field, a Paperless API change — quarantining each
document one at a time would still burn one LLM call per document across the
whole queue before anything stopped.

The breaker (`src/common/circuit_breaker.py`) is the guard against that one-pass
burn. It counts **consecutive** failed write-backs:

```mermaid
flowchart TD
    OK["processing"] -->|"write-back SAVED"| OK
    OK -->|"write-back QUARANTINED"| COUNT["failures += 1"]
    COUNT -->|"< threshold"| OK
    COUNT -->|"≥ threshold (default 3)"| TRIP["TRIPPED — halt"]
    TRIP -->|"halt_check returns a reason"| SKIP["poll skipped:\nno work fetched,\nheartbeat shows halted"]
    SKIP --> TRIP
    TRIP -->|"config change / restart"| OK
```

- A single success resets the streak, so one unlucky bad document never trips it.
- Once tripped, the polling loop's `halt_check` skips every poll — **no work is
  fetched and no tokens are spent** — and the daemon's heartbeat reports the halt
  on the Index dashboard.
- The breaker is reset by a **configuration change** (the operator's signal the
  cause may be fixed) or a restart. It is per-process and in-memory: two daemon
  instances each keep their own and halt independently.

---

## Processing-lock claims (multi-instance)

When `OCR_PROCESSING_TAG_ID` or `CLASSIFY_PROCESSING_TAG_ID` is set, each daemon
uses a best-effort optimistic lock to stop two instances processing the same
document (`src/common/claims.py`):

```mermaid
flowchart TD
    A["worker picks up document"] --> B["refresh from Paperless"]
    B --> C{"lock tag\nalready present?"}
    C -- yes --> SKIP["skip — another instance has it"]
    C -- no --> D["patch the lock tag on"]
    D --> E["re-fetch to verify"]
    E --> F{"lock tag\nstill present?"}
    F -- no --> SKIP
    F -- yes --> G["process"]
    G --> H["release lock (finally)"]
```

This eliminates almost all duplicate processing but is **not** a strict
distributed lock — in a rare race a document may be processed twice. That is
safe because the operations are idempotent.

---

## Stale-lock recovery (tag daemons)

If a daemon crashes mid-processing it leaves a document carrying a
processing-lock tag and no daemon working on it. On startup each tag daemon
sweeps for these (`src/common/stale_lock.py`):

1. Find every document carrying its processing-lock tag.
2. Remove the lock tag and re-add the queue tag.
3. The document is picked up again on the next poll.

This is why a crashed daemon never leaves work permanently stuck. (It runs only
when a processing-lock tag is configured.)

---

## The indexer's single-writer lock

The indexer is the **sole writer** of `index.db`, and it enforces that with an
OS-level exclusive `flock` on a companion `<index.db>.lock` file
(`src/indexer/lock.py`). On startup it takes the lock non-blocking; if another
indexer already holds it, the new process logs `CRITICAL` and **exits non-zero**
rather than risk two writers corrupting the index. The lock is held for the
process lifetime and released when the handle closes.

This is a structural guarantee, not a convention: the search server reaches the
index only through the write-free `StoreReader` API, and the `flock` stops a
second writer — so a bug on the read side has no write surface to misuse, and a
mis-deployment of two indexers fails fast and loud (`CODE_GUIDELINES.md` §8.4,
§10.5).

For recovering a genuinely corrupt index, see
[Store — Corruption Recovery](store.md#corruption-recovery).

---

## Indexer cycle isolation & crash safety

The indexer's reconcile loop wraps each cycle's sync/sweep/checkpoint in a
fault-isolation boundary (`src/indexer/daemon/_loop.py`): a transient failure
anywhere in a cycle is logged with its traceback, and the loop falls through to
its wait and retries next cycle. A failed cycle never advances the deletion-sweep
clock, so a missed sweep is simply retried.

Crash safety comes from the store's transaction discipline: a document's upsert —
delete its old chunks, vectors and FTS rows, insert the new ones, update its
metadata row — is **one transaction**. A crash mid-document leaves the previous
version fully intact; there is never a half-indexed document
(`CODE_GUIDELINES.md` §9.6).

---

## Graceful shutdown

Every daemon and the search server respond to **SIGINT** (Ctrl-C) and **SIGTERM**
(`docker stop`) via a thread-safe flag (`src/common/shutdown.py`):

1. The signal handler sets the flag.
2. The loop checks it before each sleep and exits cleanly.
3. In-flight work finishes; nothing new is started.
4. Processing-lock tags are released in `finally` blocks.
5. HTTP sessions and database handles are closed; the indexer releases its
   `flock`.

The process exits 0 on a graceful shutdown.

---

## Investigating failed documents

Documents that failed OCR or classification carry `ERROR_TAG_ID`. To investigate:

1. In Paperless, filter by the error tag to find them.
2. Find the document ID in the daemon logs — the failure is logged with full
   context.
3. Common causes:
   - Every model in the chain refused or failed (try different models, or adjust
     `OCR_REFUSAL_MARKERS`).
   - A Paperless write-back was rejected (a deleted tag, a bad
     `CLASSIFY_PERSON_FIELD_ID`, a permissions issue) — if this is systemic the
     circuit breaker will have halted the daemon; fix the cause and save config
     or restart.
   - The document is a format the image converter cannot handle.
4. To retry: remove `ERROR_TAG_ID` and re-add the queue tag (`PRE_TAG_ID` for
   OCR, `CLASSIFY_PRE_TAG_ID` for classification).
