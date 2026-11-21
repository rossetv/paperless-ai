import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SettingsTextField.module.css';

export interface SettingsTextFieldProps {
  /** Element id — the settings Row associates its label with this via htmlFor. */
  id: string;
  /** Accessible name. Set as aria-label; the visible label is on the Row. */
  label: string;
  /** Current field value. Controlled. */
  value: string;
  /** Called with the new value on every keystroke. */
  onChange: (value: string) => void;
  /** Input type. Defaults to 'text'. 'password' masks the value. */
  type?: 'text' | 'password';
  /** Placeholder text shown when the field is empty. */
  placeholder?: string;
  /** Render in a monospace face — for URLs, tokens, identifiers. */
  mono?: boolean;
  /** When true the field is shown but cannot be edited (bootstrap keys). */
  readOnly?: boolean;
  /** Optional element pinned to the right edge — e.g. a "Reveal" button. */
  suffix?: React.ReactNode;
  className?: string;
}

/**
 * Controlled text field for the Settings screen. Unlike `Input` it renders no
 * `<label>` (the settings `Row` owns it), has no `error` prop, and supports a
 * monospace face and an inline suffix such as a "Reveal" button.
 */
export function SettingsTextField({
  id,
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  mono = false,
  readOnly = false,
  suffix,
  className,
}: SettingsTextFieldProps): React.ReactElement {
  return (
    <div className={cn(styles['wrapper'], className)}>
      <input
        id={id}
        type={type}
        aria-label={label}
        value={value}
        placeholder={placeholder}
        readOnly={readOnly}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          styles['input'],
          mono && styles['input-mono'],
          suffix !== undefined && styles['input-with-suffix'],
        )}
      />
      {suffix !== undefined && <span className={styles['suffix']}>{suffix}</span>}
    </div>
  );
}
