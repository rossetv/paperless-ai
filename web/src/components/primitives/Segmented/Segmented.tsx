import React, { useRef } from 'react';
import { cn } from '../../../lib/cn';
import styles from './Segmented.module.css';

/** One choice in a {@link Segmented} control. */
export interface SegmentedOption {
  /** The value reported to `onChange` — never displayed. */
  value: string;
  label: string;
  /**
   * Disable just this option (greyed, not selectable) while the rest stay live.
   * Used to lock the "Ollama" provider choice until its connection is
   * configured. A whole-control `disabled` still overrides every option.
   */
  disabled?: boolean;
  /** Optional native tooltip, e.g. why a disabled option is unavailable. */
  title?: string;
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
  disabled?: boolean;
  className?: string;
}

/**
 * Controlled single-choice segmented control, rendered as a `role="radiogroup"`
 * of `role="radio"` buttons. Clicking the selected segment does not re-fire
 * `onChange`.
 */
export function Segmented({
  options,
  value,
  onChange,
  label,
  disabled = false,
  className,
}: SegmentedProps): React.ReactElement {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const isEnabled = (option: SegmentedOption): boolean =>
    !disabled && !(option.disabled ?? false);
  // Roving tabindex: the checked radio is the one tab stop; fall back to the
  // first enabled one when the checked option is missing or disabled.
  const tabStop = options.some((o) => o.value === value && isEnabled(o))
    ? value
    : options.find(isEnabled)?.value;

  function handleKeyDown(event: React.KeyboardEvent, index: number): void {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowDown'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? -1
          : 0;
    if (step === 0) return;
    event.preventDefault();
    const count = options.length;
    for (let i = 1; i <= count; i += 1) {
      const nextIndex = (index + step * i + count * i) % count;
      const next = options[nextIndex];
      if (next !== undefined && isEnabled(next)) {
        buttonRefs.current[nextIndex]?.focus();
        if (next.value !== value) onChange(next.value);
        return;
      }
    }
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(styles['group'], disabled && styles['group-disabled'], className)}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        const optionDisabled = disabled || (option.disabled ?? false);
        return (
          <button
            key={option.value}
            ref={(el) => {
              buttonRefs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={option.value === tabStop ? 0 : -1}
            disabled={optionDisabled}
            onKeyDown={(event) => handleKeyDown(event, index)}
            {...(option.title !== undefined ? { title: option.title } : {})}
            onClick={() => {
              if (!selected && !optionDisabled) {
                onChange(option.value);
              }
            }}
            className={cn(
              styles['segment'],
              selected && styles['segment-selected'],
              option.disabled && styles['segment-disabled'],
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
