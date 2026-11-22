/**
 * Label + value row with inline editing: click to edit, Enter or blur commits,
 * Escape reverts. `onCommit` fires only when the value changed.
 */
import React from 'react';
import styles from './EditableField.module.css';

export interface EditableFieldProps {
  label: string;
  /**
   * Raw value the input edits and `onCommit` receives. For `type="date"` it
   * must be `YYYY-MM-DD` so the native date input accepts it.
   */
  value: string;
  /**
   * Text shown in view mode instead of `value`, e.g. a formatted date. An
   * empty `value` still shows the placeholder.
   */
  displayValue?: string;
  canEdit: boolean;
  /** Text shown when `value` is empty. */
  placeholder?: string;
  type?: 'text' | 'number' | 'date';
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
  const shownText = displayValue ?? value;
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(value);

  // Sync the draft when the upstream value changes, but not mid-edit.
  React.useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const buttonRef = React.useRef<HTMLButtonElement>(null);
  // Set by Enter and Escape; a blur commit leaves focus where the person put it.
  const restoreFocus = React.useRef(false);

  React.useEffect(() => {
    if (editing || !restoreFocus.current) return;
    restoreFocus.current = false;
    buttonRef.current?.focus();
  }, [editing]);

  function commit(): void {
    setEditing(false);
    if (draft !== value) onCommit(draft);
  }

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
              restoreFocus.current = true;
              commit();
            } else if (e.key === 'Escape') {
              restoreFocus.current = true;
              setDraft(value);
              setEditing(false);
            }
          }}
        />
      </div>
    );
  }

  return (
    <div className={styles['row']}>
      <div className={styles['label']}>{label}</div>
      <button
        ref={buttonRef}
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
