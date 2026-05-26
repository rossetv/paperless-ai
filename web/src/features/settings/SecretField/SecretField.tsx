import React, { useState } from 'react';
import { cn } from '../../../lib/cn';
import { SettingsTextField } from '../../../components/primitives/SettingsTextField/SettingsTextField';
import styles from './SecretField.module.css';

export interface SecretFieldProps {
  /** Element id — the settings Row associates its label via htmlFor. */
  id: string;
  /** Accessible field name. */
  label: string;
  /** The server-provided MASK of the stored secret — never the real value. */
  maskedValue: string;
  /**
   * Called when the secret-change intent changes:
   *  - a string  — the new secret the user is typing,
   *  - null      — the user is NOT changing this key (initial state, or after
   *    Cancel). The screen treats null as "omit this key from the PUT body".
   */
  onChange: (value: string | null) => void;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * The control for a secret configuration key.
 *
 * The backend never sends a real secret — only a mask. So the field starts
 * locked on that mask and reports `null` (no change). Clicking "Replace"
 * switches it to an empty editable input; from then on each keystroke is
 * reported as the new secret. "Cancel" restores the locked mask and reports
 * `null` again. While replacing, a reveal toggle flips password ↔ text so the
 * user can check what they typed.
 *
 * This two-state design is what lets the screen omit an unchanged secret from
 * the save payload — an untouched SecretField never reports a string.
 *
 * Tier: features/ — composes primitives and owns the secret-handling policy.
 */
export function SecretField({
  id,
  label,
  maskedValue,
  onChange,
  className,
}: SecretFieldProps): React.ReactElement {
  const [replacing, setReplacing] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [draft, setDraft] = useState('');

  const startReplace = (): void => {
    setReplacing(true);
    setRevealed(false);
    setDraft('');
    onChange('');
  };

  const cancelReplace = (): void => {
    setReplacing(false);
    setRevealed(false);
    setDraft('');
    onChange(null);
  };

  const handleType = (value: string): void => {
    setDraft(value);
    onChange(value);
  };

  return (
    <div className={cn(styles['field'], className)}>
      <SettingsTextField
        id={id}
        label={label}
        mono
        className={styles['input']!}
        value={replacing ? draft : maskedValue}
        readOnly={!replacing}
        type={replacing && !revealed ? 'password' : 'text'}
        onChange={handleType}
        suffix={
          replacing ? (
            <button
              type="button"
              className={styles['reveal']}
              onClick={() => setRevealed((r) => !r)}
            >
              {revealed ? 'Hide' : 'Reveal'}
            </button>
          ) : undefined
        }
      />
      {replacing ? (
        <button
          type="button"
          className={styles['btn-ghost']}
          onClick={cancelReplace}
        >
          Cancel
        </button>
      ) : (
        <button
          type="button"
          className={styles['btn-ghost']}
          onClick={startReplace}
        >
          Replace
        </button>
      )}
    </div>
  );
}
