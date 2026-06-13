import React from 'react';
import styles from './DocumentTitle.module.css';

export interface DocumentTitleProps {
  /** The document title; renders a fallback when null. */
  title: string | null;
  /** Whether the current user may edit the title. */
  canEdit: boolean;
  /**
   * Called with the trimmed new title when the user commits an edit.
   * Not called on revert, Escape, or when the value is unchanged.
   */
  onChange: (next: string) => void;
}

/**
 * Document title heading with optional inline editing.
 *
 * Read-only (`canEdit=false`): renders a plain `<h1>` — correct heading
 * semantics for assistive tech.
 *
 * Editable (`canEdit=true`): the `<h1>` carries `role="button"` and responds
 * to click / Enter by switching to an `<input>`. Blur or Enter commits the
 * value (only fires `onChange` when it actually changed); Escape reverts.
 */
export function DocumentTitle({
  title,
  canEdit,
  onChange,
}: DocumentTitleProps): React.ReactElement {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(title ?? '');

  // Keep draft in sync when the parent document is refreshed (e.g. post-save),
  // but never clobber an in-progress edit: a cache refresh while the user is
  // typing must not overwrite their unsaved draft (FE-24).
  React.useEffect(() => {
    if (!editing) setDraft(title ?? '');
  }, [title, editing]);

  function commit(): void {
    setEditing(false);
    const next = draft.trim();
    if (next !== (title ?? '')) onChange(next);
  }

  if (editing) {
    return (
      <input
        className={styles['title-input']}
        value={draft}
        autoFocus
        aria-label="Document title"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { setDraft(title ?? ''); setEditing(false); }
        }}
      />
    );
  }

  return (
    <h1
      className={styles['title']}
      role={canEdit ? 'button' : undefined}
      tabIndex={canEdit ? 0 : undefined}
      aria-label={canEdit ? `Edit title: ${title ?? 'Untitled document'}` : undefined}
      onClick={canEdit ? () => setEditing(true) : undefined}
      onKeyDown={
        canEdit
          ? (e) => {
              // Enter and Space both enter edit mode; preventDefault on both so
              // Space doesn't scroll the page and the activation matches a
              // native button's keyboard contract (FE-25).
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setEditing(true);
              }
            }
          : undefined
      }
    >
      {title ?? 'Untitled document'}
    </h1>
  );
}
