/**
 * Index-operations wire types — Wave 6.
 *
 * Daemon status, reconcile-activity history, failed documents, and the
 * rebuild endpoint. Mirrors `IndexStatusResponse`, `IndexActivityResponse`,
 * `IndexFailedResponse`, and `RebuildResponse` in `wire.py`.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

/**
 * The run-state of a worker daemon.
 *
 * `running` — actively processing work; `idle` — alive but with nothing to
 * do (e.g. the indexer between reconcile cycles); `stopped` — the daemon is
 * not running or has missed its heartbeat window.
 */
export type DaemonState = 'running' | 'idle' | 'stopped';

/**
 * One worker daemon's status, as published to the Index dashboard.
 *
 * Matches `DaemonStatusResponse` in `wire.py` exactly.
 *
 * `name` is the daemon identifier (ocr / classifier / indexer / search).
 * `detail` is a short human sentence describing the last activity.
 * `processed_count` is the daemon's monotonic throughput counter.
 * `last_heartbeat` is an ISO-8601 UTC timestamp.
 */
export interface DaemonStatus {
  name: string;
  state: DaemonState;
  detail: string;
  processed_count: number;
  last_heartbeat: string;
}

/**
 * The overall index health verdict.
 *
 * Matches the `health` field of `IndexStatusResponse` in `wire.py`.
 * `"ok"` — all daemons healthy; `"degraded"` — some daemons stopped;
 * `"down"` — all daemons stopped or index unreadable.
 */
export type IndexHealthStatus = 'ok' | 'degraded' | 'down';

/**
 * Response body for GET /api/index/status.
 *
 * Matches `IndexStatusResponse` in `wire.py` exactly.
 */
export interface IndexStatusResponse {
  health: IndexHealthStatus;
  daemons: DaemonStatus[];
}

/**
 * One recorded reconcile or sweep cycle in the activity history.
 *
 * Matches `ReconcileCycleResponse` in `wire.py` exactly.
 *
 * `id` is a stable integer key for React lists. `kind` is `"sync"` or
 * `"sweep"`. `ok` drives the leading dot colour. `summary` is the cycle's
 * count map (e.g. `{"indexed": 3, "failed": 0}`). `started_at` /
 * `finished_at` are ISO-8601 UTC timestamps.
 */
export interface ReconcileCycle {
  id: number;
  kind: string;
  started_at: string;
  finished_at: string;
  ok: boolean;
  summary: Record<string, number>;
  detail: string;
}

/**
 * Response body for GET /api/index/activity.
 *
 * Matches `IndexActivityResponse` in `wire.py` exactly.
 */
export interface IndexActivityResponse {
  cycles: ReconcileCycle[];
}

/**
 * One document that failed OCR, classification or indexing.
 *
 * Matches `FailedDocumentResponse` in `wire.py` exactly.
 *
 * `title` is `null` when the document has no indexed row.
 * `failure_count` is the number of consecutive cycles it has failed.
 */
export interface FailedDocument {
  document_id: number;
  title: string | null;
  failure_count: number;
}

/** Response body for GET /api/index/failed. */
export interface IndexFailedResponse {
  documents: FailedDocument[];
}

/**
 * Response body for POST /api/index/rebuild.
 *
 * Matches `RebuildResponse` in `wire.py` exactly.
 *
 * `accepted` is true when the sentinel was written successfully.
 * `detail` is a human-readable note describing what happens next.
 */
export interface RebuildResponse {
  accepted: boolean;
  detail: string;
}
