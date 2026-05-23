import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Toggle.module.css';

export interface ToggleProps {
  /** Whether the switch is on. This is a controlled component. */
  checked: boolean;
  /** Called with the new value when the user flips the switch. */
  onChange: (checked: boolean) => void;
  /** Accessible label — there is no visible text inside the switch itself. */
  label: string;
  /** Whether the switch is non-interactive. */
  disabled?: boolean;
  /** Additional class names to merge onto the switch. */
  className?: string;
}

/**
 * An iOS-style on/off switch.
 *
 * A controlled primitive: the parent owns `checked` and updates it from
 * `onChange`. Rendered as a `<button role="switch">` so it is reachable by
 * keyboard and announced correctly by screen readers — Space/Enter activate
 * it natively because it is a real button.
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
 */
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  className,
}: ToggleProps): React.ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(styles['toggle'], checked && styles['toggleOn'], className)}
    >
      <span
        aria-hidden="true"
        className={cn(styles['knob'], checked && styles['knobOn'])}
      />
    </button>
  );
}
