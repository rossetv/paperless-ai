import React from 'react';
import styles from './SaveStatusPill.module.css';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error' | 'readonly';

export interface SaveStatusPillProps {
  status: SaveStatus;
  onRetry?: () => void;
}

const LABELS: Record<SaveStatus, string> = {
  idle: 'Saved',
  saving: 'Saving…',
  saved: 'Saved',
  error: "Couldn't save — retry",
  readonly: 'View only',
};

/**
 * Document save-state pill: a coloured dot and a label.
 *
 * The error state is a retry `<button>` with a separate hidden alert beside it;
 * putting `role="alert"` on the button itself would strip its button semantics.
 */
export function SaveStatusPill({
  status,
  onRetry,
}: SaveStatusPillProps): React.ReactElement {
  if (status === 'error' && onRetry !== undefined) {
    return (
      <>
        <button
          type="button"
          className={`${styles['pill']} ${styles['pill-error']}`}
          onClick={onRetry}
        >
          <span className={styles['dot']} />
          {LABELS[status]}
        </button>
        <span role="alert" className="visually-hidden">
          {LABELS[status]}
        </span>
      </>
    );
  }

  return (
    <span
      className={`${styles['pill']} ${styles[`pill-${status}`]}`}
      role="status"
      aria-live="polite"
    >
      <span className={styles['dot']} />
      {LABELS[status]}
    </span>
  );
}
