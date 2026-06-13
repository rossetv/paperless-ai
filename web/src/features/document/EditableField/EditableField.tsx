/**
 * EditableField — generic label + value row with inline editing.
 *
 * Renders a label alongside a value. When `canEdit` is true, clicking the
 * value switches it to an `<input>`. Pressing Enter or blurring commits the
 * new value; pressing Escape reverts to the original. Only fires `onCommit`
 * when the value actually changed.
 */
import React from 'react';
import styles from './EditableField.module.css';

export interface EditableFieldProps {
  /** Column label shown to the left of the value. */
  label: string;
  /**
   * Underlying value: pre-fills the `<input>`, drives change detection, and is
   * passed to `onCommit`. For a `type="date"` field this must be `YYYY-MM-DD`
   * so the native date input accepts it.
   */
  value: string;
  /**
   * Human-readable text shown in view mode (read-only, and the editable view
   * button). When omitted, `value` itself is displayed. Use this to show a
   * formatted date (e.g. "13 Jan 2026") while `value` stays the raw ISO the
   * input and `onCommit` operate on. An empty `value` still renders the
   * placeholder regardless of `displayValue`.
   */
  displayValue?: string;
  /** Whether the field can be clicked into edit mode. */
  canEdit: boolean;
  /** Text shown when `value` is empty. Defaults to '—'. */
  placeholder?: string;
  /** HTML input type forwarded to the underlying `<input>`. Defaults to 'text'. */
  type?: 'text' | 'number' | 'date';
  /** Called with the new value after a successful commit. Not called on revert or no-change. */
  onCommit: (next: string) => void;
}

export function EditableField({
  label,
  value,
  displayValue,
  canEdit,
  placeholder = '—',
  type = 'text',
  onCommit,
}: EditableFieldProps): React.ReactElement {
  // View-mode text: the human-readable display when supplied, else the raw
  // value. An empty value always shows the placeholder, never a formatted
  // empty string.
  const shownText = displayValue ?? value;
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(value);

  // Keep the draft in sync when the upstream value changes while not editing
  // (e.g. an external save refreshes the document).
  React.useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  function commit(): void {
    setEditing(false);
    if (draft !== value) onCommit(draft);
  }

  // ── Read-only mode ──────────────────────────────────────────────────────────
  if (!canEdit) {
    return (
      <div className={styles['row']}>
        <div className={styles['label']}>{label}</div>
        <div className={styles['value']}>
          {value === '' ? <span className={styles['empty']}>{placeholder}</span> : shownText}
        </div>
      </div>
    );
  }

  // ── Edit mode ───────────────────────────────────────────────────────────────
  if (editing) {
    return (
      <div className={styles['row']}>
        <div className={styles['label']}>{label}</div>
        <input
          className={styles['input']}
          type={type}
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commit();
            } else if (e.key === 'Escape') {
              setDraft(value);
              setEditing(false);
            }
          }}
        />
      </div>
    );
  }

  // ── View mode (editable) ────────────────────────────────────────────────────
  return (
    <div className={styles['row']}>
      <div className={styles['label']}>{label}</div>
      <button
        type="button"
        className={styles['value-button']}
        onClick={() => {
          setDraft(value);
          setEditing(true);
        }}
      >
        {value === '' ? <span className={styles['empty']}>{placeholder}</span> : shownText}
      </button>
    </div>
  );
}
