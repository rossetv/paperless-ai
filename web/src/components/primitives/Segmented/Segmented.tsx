import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Segmented.module.css';

/** One choice in a {@link Segmented} control. */
export interface SegmentedOption {
  /** The value reported to `onChange` — never displayed. */
  value: string;
  /** The visible segment label. */
  label: string;
}

export interface SegmentedProps {
  /** The selectable options, left to right. */
  options: SegmentedOption[];
  /** The currently-selected option value. Controlled. */
  value: string;
  /** Called with the new value when a different segment is chosen. */
  onChange: (value: string) => void;
  /** Accessible label for the whole control. */
  label: string;
  /** Whether the control is non-interactive. */
  disabled?: boolean;
  /** Additional class names to merge onto the group. */
  className?: string;
}

/**
 * A horizontal single-choice control — the Apple "segmented control".
 *
 * A controlled primitive: the parent owns `value` and updates it from
 * `onChange`. Rendered as a `role="radiogroup"` of `role="radio"` buttons so
 * it is announced as a single-choice group. Clicking the already-selected
 * segment is a no-op (it does not re-fire `onChange`).
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
 */
export function Segmented({
  options,
  value,
  onChange,
  label,
  disabled = false,
  className,
}: SegmentedProps): React.ReactElement {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(styles['group'], disabled && styles['groupDisabled'], className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => {
              if (!selected) {
                onChange(option.value);
              }
            }}
            className={cn(
              styles['segment'],
              selected && styles['segmentSelected'],
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
