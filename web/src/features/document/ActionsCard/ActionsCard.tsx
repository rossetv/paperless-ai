import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Button } from '../../../components/primitives/Button/Button';
import { DeleteConfirmModal } from '../DeleteConfirmModal/DeleteConfirmModal';
import { errorDetail } from '../../../api/client';
import styles from './ActionsCard.module.css';

/** Access level of the current user — drives which actions are shown. */
export type Role = 'admin' | 'member' | 'readonly';

export interface ActionsCardProps {
  documentId: number;
  /** Shown in the delete confirmation modal. */
  title: string;
  role: Role;
  onReclassify: (id: number) => void;
  onRetranscribe: (id: number) => void;
  /**
   * Called only after the user confirms in the modal, which stays open until the
   * returned promise settles: closed when it resolves, showing the error when it rejects.
   */
  onDelete: (id: number) => Promise<void>;
  /** True while that action's request runs; its button is disabled meanwhile. */
  reclassifying?: boolean;
  retranscribing?: boolean;
  deleting?: boolean;
}

/**
 * Sidebar card with the document actions. Readonly users get null, members get
 * Re-classify and Re-transcribe, admins also get Delete behind a confirmation
 * modal. The caller owns the mutation lifecycle (pending state, toasts,
 * navigation after delete) and reports it through the pending props.
 */
export function ActionsCard({
  documentId,
  title,
  role,
  onReclassify,
  onRetranscribe,
  onDelete,
  reclassifying = false,
  retranscribing = false,
  deleting = false,
}: ActionsCardProps): React.ReactElement | null {
  const [confirming, setConfirming] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  if (role === 'readonly') return null;

  return (
    <Card>
      <h3 className={styles['heading']}>Actions</h3>
      <div className={styles['actions']}>
        <Button
          variant="secondary"
          size="small"
          disabled={reclassifying}
          onClick={() => onReclassify(documentId)}
        >
          Re-classify with AI
        </Button>
        <Button
          variant="secondary"
          size="small"
          disabled={retranscribing}
          onClick={() => onRetranscribe(documentId)}
        >
          Re-transcribe with AI
        </Button>
        {role === 'admin' && (
          <Button
            variant="destructive"
            size="small"
            disabled={deleting}
            onClick={() => setConfirming(true)}
          >
            Delete document
          </Button>
        )}
      </div>

      {confirming && (
        <DeleteConfirmModal
          title={title}
          pending={deleting}
          error={deleteError}
          onCancel={() => {
            if (deleting) return;
            setConfirming(false);
            setDeleteError(null);
          }}
          onConfirm={() => {
            if (deleting) return;
            setDeleteError(null);
            onDelete(documentId).then(
              () => setConfirming(false),
              (err: unknown) => setDeleteError(errorDetail(err, "Couldn't delete the document.")),
            );
          }}
        />
      )}
    </Card>
  );
}
