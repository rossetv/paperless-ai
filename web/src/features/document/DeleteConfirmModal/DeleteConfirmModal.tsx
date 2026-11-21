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
}

/**
 * Asks the user to confirm an irreversible document deletion. Always open: the
 * parent mounts and unmounts it instead of toggling `isOpen`.
 */
export function DeleteConfirmModal({
  title,
  onCancel,
  onConfirm,
}: DeleteConfirmModalProps): React.ReactElement {
  return (
    <Modal isOpen title="Delete document" onClose={onCancel}>
      <p className={styles['body']}>
        Delete <strong>{title}</strong>? This deletes the document in
        Paperless-ngx — it cannot be undone here.
      </p>
      <div className={styles['buttons']}>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={onConfirm}>
          Delete
        </Button>
      </div>
    </Modal>
  );
}
