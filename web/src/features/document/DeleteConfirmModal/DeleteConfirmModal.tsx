/**
 * DeleteConfirmModal — accessible confirmation dialog for document deletion.
 *
 * Rendered via `ActionsCard` when the admin clicks "Delete document". The
 * modal presents the document title and two outcomes: cancel (no-op) or
 * confirm (fires `onConfirm`). The caller is responsible for triggering the
 * actual DELETE mutation after `onConfirm` fires.
 *
 * Tier: features/document — composes the Modal pattern and Button primitives.
 */
import React from 'react';
import { Modal } from '../../../components/patterns/Modal/Modal';
import { Button } from '../../../components/primitives/Button/Button';
import styles from './DeleteConfirmModal.module.css';

export interface DeleteConfirmModalProps {
  /** Title of the document being deleted — shown in the confirmation copy. */
  title: string;
  /** Called when the user dismisses the modal without confirming. */
  onCancel: () => void;
  /** Called when the user confirms the deletion. */
  onConfirm: () => void;
}

/**
 * Asks the user to confirm an irreversible document deletion.
 *
 * Always rendered open (the parent mounts/unmounts rather than toggling
 * `isOpen`) so the prop wires directly to `isOpen={true}`.
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
