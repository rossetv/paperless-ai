import React from 'react';
import { cn } from '../../../lib/cn';
import { Button } from '../../../components/primitives/Button/Button';
import { StatusBadge } from '../../../components/primitives/StatusBadge/StatusBadge';
import type { FailedDocument } from '../../../api/types';
import styles from './FailedDocumentsPanel.module.css';

export interface FailedDocumentsPanelProps {
  /** The failed documents, from GET /api/index/failed. */
  documents: FailedDocument[];
  /** Called with a document id when its "View" button is pressed. */
  onOpen: (documentId: number) => void;
  className?: string;
}

/**
 * The Index dashboard failed-documents panel.
 *
 * Header with a count badge, a card per failed document (id chip, title,
 * failure count, "View" action). An empty list shows an all-clear line.
 *
 * There is no per-document retry: the indexer re-processes failed documents
 * on its next reconcile cycle.
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
                <Button
                  variant="ghost"
                  size="small"
                  aria-label={`View document ${doc.document_id}: ${doc.title ?? '(no title)'}`}
                  onClick={() => onOpen(doc.document_id)}
                >
                  View
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
