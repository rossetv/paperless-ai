import React, { useState, useEffect } from 'react';
import { cn } from '../../../lib/cn';
import styles from './NumberStepper.module.css';

export interface NumberStepperProps {
  /** The current numeric value. Controlled. */
  value: number;
  /** Called with the new (clamped) value on any change. */
  onChange: (value: number) => void;
  /** Accessible label for the value field. */
  label: string;
  /** Smallest permitted value. Defaults to 0. */
  min?: number;
  /** Largest permitted value. Defaults to Number.MAX_SAFE_INTEGER. */
  max?: number;
  /** Step applied by the − / + buttons. Defaults to 1. */
  step?: number;
  /** Optional unit shown after the field — "s", "px", "chars". */
  suffix?: string;
  /** Whether the control is non-interactive. */
  disabled?: boolean;
  /** Additional class names to merge onto the control. */
  className?: string;
}

/**
 * A numeric input with − / + stepper buttons and an optional unit suffix.
 *
 * A controlled primitive. The value is clamped to `[min, max]` on every
 * change — whether from a button or a keystroke — so a consumer never
 * receives an out-of-range number. A blank field is treated as `min`
 * (clearing then retyping is a normal editing gesture).
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
 */
export function NumberStepper({
  value,
  onChange,
  label,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  step = 1,
  suffix,
  disabled = false,
  className,
}: NumberStepperProps): React.ReactElement {
  // Local draft string tracks in-progress editing so the field does not
  // re-sync to the prop value on every keystroke while the user is typing.
  const [draft, setDraft] = useState(String(value));

  // When the prop value changes externally (e.g. stepper buttons), sync draft.
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const clamp = (n: number): number => Math.min(max, Math.max(min, n));

  const emit = (n: number): void => {
    const clamped = clamp(n);
    onChange(clamped);
  };

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const raw = event.target.value;
    setDraft(raw);
    // A blank field maps to the minimum — a transient state while editing.
    const parsed = raw === '' ? min : Number(raw);
    if (!Number.isNaN(parsed)) {
      emit(parsed);
    }
  };

  return (
    <div
      className={cn(styles['stepper'], disabled && styles['stepperDisabled'], className)}
    >
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        disabled={disabled || value <= min}
        onClick={() => emit(value - step)}
        className={styles['button']}
      >
        −
      </button>
      <input
        type="number"
        aria-label={label}
        value={draft}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={handleChange}
        className={styles['input']}
      />
      {suffix !== undefined && <span className={styles['suffix']}>{suffix}</span>}
      <button
        type="button"
        aria-label={`Increase ${label}`}
        disabled={disabled || value >= max}
        onClick={() => emit(value + step)}
        className={styles['button']}
      >
        +
      </button>
    </div>
  );
}
