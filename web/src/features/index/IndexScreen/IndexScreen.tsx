import React, { useState } from 'react';
import { Button } from '../../../components/primitives/Button/Button';
import { Link } from '../../../components/primitives/Link/Link';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { useAuth } from '../../../hooks/useAuth';
import {
  useIndexStatus,
  useIndexActivity,
  useFailedDocuments,
  useStats,
  useReconcile,
} from '../../../api/hooks';
import { IndexHealthHero } from '../IndexHealthHero/IndexHealthHero';
import { StatTile } from '../../../components/primitives/StatTile/StatTile';
import { DaemonCard } from '../DaemonCard/DaemonCard';
import { ActivityRow } from '../ActivityRow/ActivityRow';
import { FailedDocumentsPanel } from '../FailedDocumentsPanel/FailedDocumentsPanel';
import { RebuildIndexCard } from '../RebuildIndexCard/RebuildIndexCard';
import { DocumentPreviewScreen } from '../../search/DocumentPreviewScreen/DocumentPreviewScreen';
import { relativeTime } from '../../../lib/relativeTime';
import styles from './IndexScreen.module.css';

/** Number of activity rows to show before the "View full log" link appears. */
const ACTIVITY_ROW_LIMIT = 5;

/**
 * The Index operations dashboard.
 *
 * Composes the health hero, a stat-tile row (from GET /api/stats), the
 * daemon-status cards, the reconcile-activity list, the failed-documents
 * panel and — for an admin — the destructive rebuild card. Owns the status /
 * activity / failed-document / stats queries (the first two poll) and the
 * reconcile mutation.
 *
 * Holds `previewDocumentId` state: when a failed-document's "Preview" button
 * is clicked, `FailedDocumentsPanel` calls `onOpen(id)`, which sets this
 * state and renders the in-app `DocumentPreviewScreen` overlay.
 *
 * The status query gates the whole dashboard: while it is loading a `Spinner`
 * shows; if it errors an `EmptyState` with a warning icon shows (consistent
 * with the Library and Search error patterns); otherwise the dashboard renders. The activity and failed-document panels degrade independently —
 * each renders an empty list rather than blocking the page.
 *
 * The "Reconcile now" button is hidden for read-only callers — the backend
 * gates that endpoint on Member+ role, so showing it to readonly users would
 * produce a silent 403.
 *
 * Renders no `AppNavBar`: the `IndexPage` host wraps it, matching the Wave 1
 * page pattern.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — composes primitives, the
 * index features, api hooks and `useAuth`.
 */
export function IndexScreen(): React.ReactElement {
  const { role } = useAuth();
  const statusQuery = useIndexStatus();
  const activityQuery = useIndexActivity();
  const failedQuery = useFailedDocuments();
  const statsQuery = useStats();
  const reconcile = useReconcile();

  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);
  const [showAllActivity, setShowAllActivity] = useState(false);

  const failedDocuments = failedQuery.data?.documents ?? [];
  const stats = statsQuery.data;

  return (
    <div className={styles['screen']}>
      <header className={styles['header']}>
        <div className={styles['title-block']}>
          <h1 className={styles['title']}>Index</h1>
          <p className={styles['subtitle']}>
            Health and throughput of the local SQLite search index and the
            four daemons that keep it warm.
          </p>
        </div>
        <div className={styles['header-actions']}>
          {role !== 'readonly' && (
            <Button
              variant="secondary"
              disabled={reconcile.isPending}
              onClick={() => reconcile.mutate()}
            >
              {reconcile.isPending ? 'Reconciling…' : 'Reconcile now'}
            </Button>
          )}
          <Button
            variant="primary"
            onClick={() =>
              document
                .getElementById('recent-activity')
                ?.scrollIntoView({ behavior: 'smooth' })
            }
          >
            View live log
          </Button>
        </div>
      </header>

      {statusQuery.isLoading && (
        <div className={styles['state-box']}>
          <Spinner label="Loading the index status…" size="large" />
        </div>
      )}

      {statusQuery.isError && (
        <div className={styles['state-box']} role="alert">
          <EmptyState
            icon="warning"
            message="Could not load the index status"
            description="The search server may be unreachable — retrying automatically."
          />
        </div>
      )}

      {statusQuery.data !== undefined && (
        <div className={styles['body']}>
          <IndexHealthHero health={statusQuery.data.health} />

          {stats !== undefined && (
            <div className={styles['quad-row']}>
              <StatTile
                value={(stats.document_count ?? 0).toLocaleString('en-GB')}
                label="Documents indexed"
                {...(stats.last_reconcile_at !== null
                  ? { sub: `synced ${relativeTime(stats.last_reconcile_at)}` }
                  : {})}
                accent
              />
              <StatTile
                value={(stats.chunk_count ?? 0).toLocaleString('en-GB')}
                label="Semantic chunks"
                {...((stats.document_count ?? 0) > 0
                  ? {
                      sub: `≈ ${Math.round(
                        (stats.chunk_count ?? 0) / (stats.document_count ?? 1),
                      ).toLocaleString('en-GB')} chunks per document`,
                    }
                  : {})}
              />
              {/* sub hard-coded to the env default; no dim field is exposed by the API yet. */}
              <StatTile
                value={stats.embedding_model ?? '—'}
                label="Embedding model"
                sub="1,536 dimensions"
              />
              <StatTile
                value={
                  stats.last_reconcile_at !== null
                    ? relativeTime(stats.last_reconcile_at)
                    : '—'
                }
                label="Last reconcile"
                {...(stats.last_reconcile_at !== null
                  ? {
                      sub: new Date(stats.last_reconcile_at).toLocaleDateString(
                        'en-GB',
                      ),
                    }
                  : {})}
              />
            </div>
          )}

          <section>
            <div className={styles['section-head']}>
              <h2 className={styles['section-title']}>Daemons</h2>
              <span className={styles['section-hint']}>
                four worker processes — all running in the same container
              </span>
            </div>
            <div className={styles['quad-row']}>
              {statusQuery.data.daemons.map((daemon) => (
                <DaemonCard key={daemon.name} daemon={daemon} />
              ))}
            </div>
          </section>

          <div className={styles['split-row']}>
            <section className={styles['activity-panel']} id="recent-activity">
              <div className={styles['activity-panel-head']}>
                <h3 className={styles['activity-head']}>Recent activity</h3>
                {(activityQuery.data?.cycles ?? []).length > ACTIVITY_ROW_LIMIT && (
                  <Link
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setShowAllActivity((prev) => !prev);
                    }}
                  >
                    {showAllActivity ? 'Show less ›' : 'View full log ›'}
                  </Link>
                )}
              </div>
              <div>
                {(showAllActivity
                  ? (activityQuery.data?.cycles ?? [])
                  : (activityQuery.data?.cycles ?? []).slice(0, ACTIVITY_ROW_LIMIT)
                ).map((cycle, i, visible) => (
                  <ActivityRow
                    key={cycle.id}
                    cycle={cycle}
                    last={i === visible.length - 1}
                  />
                ))}
              </div>
            </section>

            <FailedDocumentsPanel
              documents={failedDocuments}
              onOpen={setPreviewDocumentId}
            />
          </div>

          {role === 'admin' && <RebuildIndexCard />}
        </div>
      )}

      {previewDocumentId !== null && (() => {
        const previewDoc = failedDocuments.find(
          (d) => d.document_id === previewDocumentId,
        );
        if (previewDoc === undefined) {
          return null;
        }
        // Build the SourceDocument shape DocumentPreviewScreen expects.
        // FailedDocument carries only id/title; correspondent,
        // document_type, created, snippet, score and paperless_url get
        // harmless defaults — Wave 7 reconciles the viewer interface so a
        // failed-document row can open it without fabricating these.
        const source = {
          document_id: previewDoc.document_id,
          title: previewDoc.title ?? '',
          correspondent: null,
          document_type: null,
          created: null,
          snippet: '',
          paperless_url: null,
          score: 0,
        };
        return (
          <DocumentPreviewScreen
            source={source}
            onClose={() => setPreviewDocumentId(null)}
          />
        );
      })()}
    </div>
  );
}
