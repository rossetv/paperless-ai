import React, { useState } from 'react';
import { cn } from '../../../lib/cn';
import { SettingsTextField } from '../../../components/primitives/SettingsTextField/SettingsTextField';
import styles from './SecretField.module.css';

export interface SecretFieldProps {
  /** The settings Row associates its label via htmlFor. */
  id: string;
  label: string;
  /** The server-provided MASK of the stored secret — never the real value. */
  maskedValue: string;
  /**
   * Receives the new secret being typed, or `null` when the user is not changing this key
   * (initially and after Cancel); the screen omits a `null` key from the PUT body.
   */
  onChange: (value: string | null) => void;
  className?: string;
}

/**
 * The control for a secret configuration key.
 *
 * The backend only ever sends a mask, so the field starts locked on it and reports `null`.
 * "Replace" switches to an empty input whose keystrokes are reported as the new secret;
 * "Cancel" restores the mask and reports `null` again. An untouched field therefore never
 * reports a string, which lets the screen omit an unchanged secret from the save payload.
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
              aria-pressed={revealed}
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
