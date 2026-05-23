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
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/**
 * The Apple-form text field used across the Settings screen.
 *
 * A controlled primitive. Intentionally distinct from the generic `Input`:
 *   - No `<label>` element — the settings `Row` owns the visible label and
 *     the `htmlFor` association; this component exposes `aria-label` only.
 *   - Supports a monospace face (`mono` prop) for URLs, tokens, identifiers.
 *   - Supports an inline suffix slot for "Reveal" buttons.
 *   - Uses the smaller settings-form sizing (see CSS module).
 *   - No `error` prop — settings validation is handled at the Row level.
 *
 * The split from `Input` is justified (W7 audit decision): merging would
 * either add rarely-used props to `Input` or require a `variant` that
 * changes its fundamental label-ownership contract. Keeping them separate
 * keeps both APIs honest.
 *
 * `readOnly` renders bootstrap config keys that exist but cannot be edited.
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
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
