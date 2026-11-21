import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Button } from '../../../components/primitives/Button/Button';
import { DeleteConfirmModal } from '../DeleteConfirmModal/DeleteConfirmModal';
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
  /** Called only after the user confirms in the modal. */
  onDelete: (id: number) => void;
}

/**
 * Sidebar card with the document actions. Readonly users get null, members get
 * Re-classify and Re-transcribe, admins also get Delete behind a confirmation
 * modal. The caller owns the mutation lifecycle (pending state, toasts,
 * navigation after delete).
 */
export function ActionsCard({
  documentId,
  title,
  role,
  onReclassify,
  onRetranscribe,
  onDelete,
}: ActionsCardProps): React.ReactElement | null {
  const [confirming, setConfirming] = React.useState(false);

  if (role === 'readonly') return null;

  return (
    <Card>
      <h3 className={styles['heading']}>Actions</h3>
      <div className={styles['actions']}>
        <Button
          variant="secondary"
          size="small"
          onClick={() => onReclassify(documentId)}
        >
          Re-classify with AI
        </Button>
        <Button
          variant="secondary"
          size="small"
          onClick={() => onRetranscribe(documentId)}
        >
          Re-transcribe with AI
        </Button>
        {role === 'admin' && (
          <Button
            variant="destructive"
            size="small"
            onClick={() => setConfirming(true)}
          >
            Delete document
          </Button>
        )}
      </div>

      {confirming && (
        <DeleteConfirmModal
          title={title}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            onDelete(documentId);
          }}
        />
      )}
    </Card>
  );
}
