import React from 'react';
import styles from './DocumentTitle.module.css';

export interface DocumentTitleProps {
  /** The document title; renders a fallback when null. */
  title: string | null;
  /**
   * Whether the current user may edit the title.
   * Accepted now to keep the API stable across waves; wired up in Wave B.
   */
  canEdit: boolean;
  /**
   * Called with the new title value when the user commits an edit.
   * Accepted now to keep the API stable across waves; wired up in Wave B.
   */
  onChange: (next: string) => void;
}

/**
 * Document title heading — Wave A (view-only).
 *
 * Renders the document title as an `<h1>`. Falls back to "Untitled document"
 * when `title` is null. The `canEdit` and `onChange` props are accepted now
 * so the public API does not churn when Wave B wires up inline editing.
 */
export function DocumentTitle({
  title,
  canEdit,
  onChange,
}: DocumentTitleProps): React.ReactElement {
  // Editing is wired up in Wave B; the props are accepted now to keep the API stable.
  void canEdit;
  void onChange;

  return (
    <h1 className={styles['title']}>{title ?? 'Untitled document'}</h1>
  );
}
