import React from 'react';
import { cn } from '../../../lib/cn';
import { StatusBadge } from '../../../components/primitives/StatusBadge/StatusBadge';
import type { FailedDocument } from '../../../api/types';
import styles from './FailedDocumentsPanel.module.css';

export interface FailedDocumentsPanelProps {
  /** The failed documents, from GET /api/index/failed. */
  documents: FailedDocument[];
  /** Called with a document id when its "Preview" button is pressed; opens the in-app DocumentPreviewScreen overlay. */
  onOpen: (documentId: number) => void;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * The Index dashboard failed-documents panel.
 *
 * Header with a count badge, a card per failed document (id chip, title,
 * failure count, "Preview" action). An empty list shows an all-clear line.
 *
 * The component is a pure render: `previewDocumentId` state lives in
 * `IndexScreen`, which passes `onOpen`. Retry is intentionally absent —
 * there is no `/api/index/failed/{id}/retry` endpoint; re-processing happens
 * automatically on the indexer's next reconcile cycle.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — composes the StatusBadge
 * primitive and takes a domain wire type.
 */
export function FailedDocumentsPanel({
  documents,
  onOpen,
  className,
}: FailedDocumentsPanelProps): React.ReactElement {
  const empty = documents.length === 0;

  return (
    <section className={cn(styles['panel'], className)}>
      <div className={styles['header']}>
        <h3 className={styles['heading']}>Failed documents</h3>
        <StatusBadge tone={empty ? 'ok' : 'danger'}>
          {documents.length}
        </StatusBadge>
      </div>

      {empty ? (
        <p className={styles['empty']}>
          No failed documents — every document is indexed.
        </p>
      ) : (
        <div className={styles['list']}>
          {documents.map((doc) => (
            <article key={doc.document_id} className={styles['item']}>
              <div className={styles['item-head']}>
                <span className={styles['id-chip']}>#{doc.document_id}</span>
                <span className={styles['item-title']}>
                  {doc.title ?? '(no title)'}
                </span>
              </div>
              <div className={styles['actions']}>
                <span className={styles['when']}>
                  Failed {doc.failure_count}{' '}
                  {doc.failure_count === 1 ? 'time' : 'times'}
                </span>
                <span className={styles['actions-spacer']} />
                <button
                  type="button"
                  className={styles['action']}
                  onClick={() => onOpen(doc.document_id)}
                >
                  Preview
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
