import React, { useState } from 'react';
import { Button } from '../../../components/primitives/Button/Button';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { useAuth } from '../../../hooks/useAuth';
import {
  useIndexStatus,
  useIndexActivity,
  useFailedDocuments,
  useRetryFailedDocument,
  useReconcile,
} from '../../../api/hooks';
import { IndexHealthHero } from '../IndexHealthHero/IndexHealthHero';
import { StatTile } from '../../../components/primitives/StatTile/StatTile';
import { DaemonCard } from '../DaemonCard/DaemonCard';
import { ActivityRow } from '../ActivityRow/ActivityRow';
import { FailedDocumentsPanel } from '../FailedDocumentsPanel/FailedDocumentsPanel';
import { RebuildIndexCard } from '../RebuildIndexCard/RebuildIndexCard';
import { DocumentPreviewScreen } from '../../search/DocumentPreviewScreen/DocumentPreviewScreen';
import styles from './IndexScreen.module.css';

/**
 * Format a byte count as a human-readable size — "842 MB", "1.4 GB".
 *
 * Uses 1024-based units and one decimal place above the MB threshold; bytes
 * and KB are shown whole. A non-finite or negative input falls back to "—".
 */
function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '—';
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${Math.round(kb)} KB`;
  }
  const mb = kb / 1024;
  if (mb < 1024) {
    return `${Math.round(mb)} MB`;
  }
  return `${(mb / 1024).toFixed(1)} GB`;
}

/**
 * The Index operations dashboard.
 *
 * Composes the health hero, a stat-tile row, the daemon-status cards, the
 * reconcile-activity list, the failed-documents panel and — for an admin —
 * the destructive rebuild card. Owns the status / activity / failed-document
 * queries (the first two poll) and the reconcile + retry mutations.
 *
 * Holds `previewDocumentId` state: when a failed-document's "Preview" button
 * is clicked, `FailedDocumentsPanel` calls `onOpen(id)`, which sets this
 * state and renders the in-app `DocumentPreviewScreen` overlay.
 *
 * The status query gates the whole dashboard: while it is loading a spinner
 * shows; if it errors an error message shows; otherwise the dashboard
 * renders. The activity and failed-document panels degrade independently —
 * each renders an empty list rather than blocking the page.
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
  const reconcile = useReconcile();
  const retry = useRetryFailedDocument();

  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);

  const failedDocuments = failedQuery.data?.documents ?? [];

  function handleRetryAll(): void {
    for (const doc of failedDocuments) {
      retry.mutate(doc.document_id);
    }
  }

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
        <Button
          variant="secondary"
          disabled={reconcile.isPending}
          onClick={() => reconcile.mutate()}
        >
          {reconcile.isPending ? 'Reconciling…' : 'Reconcile now'}
        </Button>
      </header>

      {statusQuery.isLoading && (
        <div className={styles['state-box']}>
          <Spinner label="Loading the index status…" size="large" />
        </div>
      )}

      {statusQuery.isError && (
        <div className={styles['state-box']}>
          <p className={styles['error-text']} role="alert">
            Could not load the index status. The search server may be
            unreachable — retrying automatically.
          </p>
        </div>
      )}

      {statusQuery.data !== undefined && (
        <div className={styles['body']}>
          <IndexHealthHero health={statusQuery.data.health} />

          <div className={styles['quad-row']}>
            <StatTile
              value={statusQuery.data.document_count.toLocaleString('en-GB')}
              label="Documents indexed"
              accent
            />
            <StatTile
              value={statusQuery.data.chunk_count.toLocaleString('en-GB')}
              label="Semantic chunks"
            />
            <StatTile
              value={statusQuery.data.embedding_model ?? '—'}
              label="Embedding model"
            />
            <StatTile
              value={formatBytes(statusQuery.data.index_size_bytes)}
              label="Index size on disk"
              sub="/data/index.db"
            />
          </div>

          <section>
            <div className={styles['section-head']}>
              <h2 className={styles['section-title']}>Daemons</h2>
              <span className={styles['section-hint']}>
                four worker processes — all running in the same container
              </span>
            </div>
            <div className={styles['quad-row']}>
              {statusQuery.data.daemons.map((daemon) => (
                <DaemonCard key={daemon.key} daemon={daemon} />
              ))}
            </div>
          </section>

          <div className={styles['split-row']}>
            <section className={styles['activity-panel']}>
              <h3 className={styles['activity-head']}>Recent activity</h3>
              <div>
                {(activityQuery.data?.entries ?? []).map((entry, i, all) => (
                  <ActivityRow
                    key={entry.id}
                    entry={entry}
                    last={i === all.length - 1}
                  />
                ))}
              </div>
            </section>

            <FailedDocumentsPanel
              documents={failedDocuments}
              onRetry={(id) => retry.mutate(id)}
              onRetryAll={handleRetryAll}
              onOpen={setPreviewDocumentId}
              retrying={retry.isPending}
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
          title: previewDoc.title,
          correspondent: null,
          document_type: null,
          created: null,
          snippet: '',
          paperless_url: '',
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
