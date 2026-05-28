/**
 * ActionsCard — document action buttons in the sidebar.
 *
 * Renders a card with AI re-classify, AI re-transcribe, and (admins only)
 * delete actions. Returns null for readonly users so it is safe to mount
 * unconditionally in `DocumentScreen`.
 *
 * The delete button opens `DeleteConfirmModal` before firing the handler —
 * an extra confirmation step to guard against accidental irreversible deletes.
 *
 * Callbacks are plain synchronous handlers; the calling component owns the
 * mutation lifecycle (isPending, error toasts, navigation-after-delete, etc.).
 *
 * Tier: features/document — composes Card, Button primitives and
 * DeleteConfirmModal.
 */
import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Button } from '../../../components/primitives/Button/Button';
import { DeleteConfirmModal } from '../DeleteConfirmModal/DeleteConfirmModal';
import styles from './ActionsCard.module.css';

/** Access level of the current user — drives which actions are shown. */
export type Role = 'admin' | 'member' | 'readonly';

export interface ActionsCardProps {
  /** Paperless-ngx document id. */
  documentId: number;
  /** Document title — passed to the delete confirmation modal. */
  title: string;
  /** Access role of the signed-in user. */
  role: Role;
  /** Called when the user triggers AI re-classification. */
  onReclassify: (id: number) => void;
  /** Called when the user triggers AI re-transcription. */
  onRetranscribe: (id: number) => void;
  /** Called when the user confirms document deletion. */
  onDelete: (id: number) => void;
}

/**
 * Sidebar card exposing document actions.
 *
 * Readonly users see nothing (returns null). Members see Re-classify and
 * Re-transcribe. Admins additionally see the Delete button guarded by a
 * confirmation modal.
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
