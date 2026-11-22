import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Button } from '../../../components/primitives/Button/Button';
import styles from './DeleteConfirmModal.module.css';

export interface DeleteConfirmModalProps {
  /** Title of the document being deleted. */
  title: string;
  onCancel: () => void;
  /** The caller runs the actual DELETE mutation. */
  onConfirm: () => void;
  /** True while the delete runs: both buttons are disabled meanwhile. */
  pending?: boolean;
  /** Why the last delete failed, shown inside the dialog. */
  error?: string | null;
}

/**
 * Asks the user to confirm an irreversible document deletion. Always open: the
 * parent mounts and unmounts it instead of toggling `isOpen`.
 */
export function DeleteConfirmModal({
  title,
  onCancel,
  onConfirm,
  pending = false,
  error = null,
}: DeleteConfirmModalProps): React.ReactElement {
  return (
    <Modal isOpen title="Delete document" onClose={onCancel}>
      <p className={styles['body']}>
        Delete <strong>{title}</strong>? This deletes the document in
        Paperless-ngx — it cannot be undone here.
      </p>
      {error !== null && (
        <p className={styles['error']} role="alert">
          {error}
        </p>
      )}
      <div className={styles['buttons']}>
        <Button variant="ghost" disabled={pending} onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="destructive" disabled={pending} onClick={onConfirm}>
          {pending ? 'Deleting…' : 'Delete'}
        </Button>
      </div>
    </Modal>
  );
}
