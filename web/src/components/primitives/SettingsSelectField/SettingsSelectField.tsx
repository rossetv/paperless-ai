import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SettingsSelectField.module.css';

/** One choice in a {@link SettingsSelectField}. */
export interface SettingsSelectOption {
  /** The value reported to `onChange`. */
  value: string;
  /** The visible option label. */
  label: string;
}

export interface SettingsSelectFieldProps {
  /** Element id — the settings Row associates its label via htmlFor. */
  id: string;
  /** Accessible name. Set as aria-label; the visible label is on the Row. */
  label: string;
  /** The currently-selected value. Controlled. */
  value: string;
  /** The available options. */
  options: SettingsSelectOption[];
  /** Called with the chosen value when the selection changes. */
  onChange: (value: string) => void;
  /** Whether the control is non-interactive. */
  disabled?: boolean;
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/**
 * A native `<select>` styled to match the Settings-screen form fields.
 *
 * A controlled primitive. If `value` is not present in `options` — a config
 * key may hold a model identifier the UI does not know about — that value is
 * injected as an extra option so it stays selectable and visible, never
 * silently dropped.
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
 */
export function SettingsSelectField({
  id,
  label,
  value,
  options,
  onChange,
  disabled = false,
  className,
}: SettingsSelectFieldProps): React.ReactElement {
  // Guarantee the current value is always one of the rendered options.
  const known = options.some((option) => option.value === value);
  const allOptions = known
    ? options
    : [{ value, label: value }, ...options];

  return (
    <div className={cn(styles['wrapper'], className)}>
      <select
        id={id}
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={styles['select']}
      >
        {allOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <svg
        aria-hidden="true"
        className={styles['chevron']}
        width="11"
        height="11"
        viewBox="0 0 12 12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <polyline points="2,4 6,8 10,4" />
      </svg>
    </div>
  );
}
