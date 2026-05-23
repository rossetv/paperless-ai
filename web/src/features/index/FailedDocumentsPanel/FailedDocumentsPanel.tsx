import { cn } from '../../../lib/cn';
import { StatusBadge } from '../../../components/primitives/StatusBadge/StatusBadge';
import { relativeTime } from '../ActivityRow/ActivityRow';
import type { FailedDocument } from '../../../api/types';
import styles from './FailedDocumentsPanel.module.css';

export interface FailedDocumentsPanelProps {
  /** The failed documents, from GET /api/index/failed. */
  documents: FailedDocument[];
  /** Called with a document id when its "Retry" button is pressed. */
  onRetry: (documentId: number) => void;
  /** Called when the "Retry all" footer button is pressed. */
  onRetryAll: () => void;
  /** Called with a document id when its "Preview" button is pressed; opens the in-app DocumentPreviewScreen overlay. */
  onOpen: (documentId: number) => void;
  /** When true, every Retry control is disabled (a retry is in flight). */
  retrying?: boolean;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * The Index dashboard failed-documents panel.
 *
 * Header with a count badge, a card per failed document (id chip, title,
 * reason, relative time, "Retry" + "Preview" actions), and a "Retry all"
 * footer. An empty list shows an all-clear line and no footer.
 *
 * The component is a pure render: the retry mutation and previewDocumentId
 * state live in `IndexScreen`, which passes `onRetry` / `onRetryAll` /
 * `onOpen` / `retrying`. While `retrying` is true every button is disabled
 * to prevent a double-submit.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — composes the StatusBadge
 * primitive, reuses `relativeTime` from the ActivityRow feature.
 */
export function FailedDocumentsPanel({
  documents,
  onRetry,
  onRetryAll,
  onOpen,
  retrying = false,
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
        <>
          <div className={styles['list']}>
            {documents.map((doc) => (
              <article key={doc.document_id} className={styles['item']}>
                <div className={styles['item-head']}>
                  <span className={styles['id-chip']}>#{doc.document_id}</span>
                  <span className={styles['item-title']}>{doc.title}</span>
                </div>
                <p className={styles['reason']}>{doc.reason}</p>
                <div className={styles['actions']}>
                  <span className={styles['when']}>
                    {relativeTime(doc.failed_at)}
                  </span>
                  <span className={styles['actions-spacer']} />
                  <button
                    type="button"
                    className={styles['action']}
                    disabled={retrying}
                    onClick={() => onRetry(doc.document_id)}
                  >
                    Retry
                  </button>
                  <button
                    type="button"
                    className={styles['action']}
                    disabled={retrying}
                    onClick={() => onOpen(doc.document_id)}
                  >
                    Preview
                  </button>
                </div>
              </article>
            ))}
          </div>
          <div className={styles['footer']}>
            <button
              type="button"
              className={styles['action']}
              disabled={retrying}
              onClick={onRetryAll}
            >
              Retry all
            </button>
          </div>
        </>
      )}
    </section>
  );
}
