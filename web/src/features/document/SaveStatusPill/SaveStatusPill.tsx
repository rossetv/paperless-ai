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
 * Save status indicator pill — shows document save state.
 *
 * Renders a small capsule with a coloured dot and label:
 *   - idle/saved: green dot, "Saved"
 *   - saving: amber dot, "Saving…"
 *   - error: red dot, "Couldn't save — retry" (interactive button with retry)
 *   - readonly: grey dot, "View only"
 *
 * Error state renders as a button (role="alert") for retry handling.
 * Other states render as a span (role="status", aria-live="polite").
 *
 * Tier: features/document (leaf component, used by DocumentScreen).
 */
export function SaveStatusPill({
  status,
  onRetry,
}: SaveStatusPillProps): React.ReactElement {
  if (status === 'error' && onRetry !== undefined) {
    return (
      <button
        type="button"
        className={`${styles['pill']} ${styles['pill-error']}`}
        role="alert"
        onClick={onRetry}
      >
        <span className={styles['dot']} />
        {LABELS[status]}
      </button>
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
