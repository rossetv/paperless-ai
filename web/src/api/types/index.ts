/** Index-operations wire types; they mirror `src/search/wire/index_dashboard.py`. */

/**
 * The run-state of a worker daemon.
 *
 * `running` — actively processing work; `idle` — alive but with nothing to
 * do (e.g. the indexer between reconcile cycles); `stopped` — the daemon is
 * not running or has missed its heartbeat window.
 */
export type DaemonState = 'running' | 'idle' | 'stopped';

/**
 * One worker daemon's status (`DaemonStatusResponse`).
 *
 * `name` is ocr / classifier / indexer / search; `detail` is a short sentence on
 * the last activity; `processed_count` only grows; `last_heartbeat` is ISO-8601 UTC.
 */
export interface DaemonStatus {
  name: string;
  state: DaemonState;
  detail: string;
  processed_count: number;
  last_heartbeat: string;
}

/**
 * The overall index health verdict: `"ok"` all daemons healthy, `"degraded"` some
 * stopped, `"down"` all stopped or the index unreadable.
 */
export type IndexHealthStatus = 'ok' | 'degraded' | 'down';

/** Response body for GET /api/index/status. */
export interface IndexStatusResponse {
  health: IndexHealthStatus;
  daemons: DaemonStatus[];
}

/**
 * One recorded reconcile or sweep cycle (`ReconcileCycleResponse`).
 *
 * `summary` is the cycle's count map, e.g. `{"indexed": 3, "failed": 0}`;
 * timestamps are ISO-8601 UTC.
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

/** Response body for GET /api/index/activity. */
export interface IndexActivityResponse {
  cycles: ReconcileCycle[];
}

/**
 * One document that failed OCR, classification or indexing (`FailedDocumentResponse`).
 *
 * `title` is `null` when the document has no indexed row; `failure_count` counts
 * consecutive failed cycles.
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
 * Response body for POST /api/index/rebuild. `accepted` is true when the rebuild
 * sentinel was written; `detail` says what happens next.
 */
export interface RebuildResponse {
  accepted: boolean;
  detail: string;
}
