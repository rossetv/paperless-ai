import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './FormField.module.css';

/**
 * The aria wiring a `FormField` hands to its control.
 *
 * The control spreads or reads these so the label, the error message, and the
 * `aria-invalid` / `aria-describedby` attributes are wired consistently — the
 * scaffolding that Input and TextArea previously hand-rolled identically.
 */
export interface FieldControlProps {
  /** Whether the field is currently showing a validation error. */
  hasError: boolean;
  /** The id of the error message element, or undefined when there is no error. */
  errorId: string | undefined;
}

export interface FormFieldProps {
  /** The control id — wires the `<label htmlFor>` and the error message id. */
  id: string;
  /**
   * Visible label text. Omit (or pass `undefined`) to label the control
   * externally — declared `| undefined` so a control can forward its own
   * optional `label` prop straight through under `exactOptionalPropertyTypes`.
   */
  label?: string | undefined;
  /** Validation error message. When set, the error region renders. */
  error?: string | undefined;
  /**
   * The control, as a render function receiving the aria wiring. The control
   * applies `hasError` / `errorId` to its own element (`aria-invalid`,
   * `aria-describedby`, an error class).
   */
  children: (control: FieldControlProps) => React.ReactNode;
  /** Additional class names to merge onto the field wrapper. */
  className?: string | undefined;
  /**
   * Surface the field is rendered on. `'dark'` switches the label, control
   * border and control background to the forced-dark island tokens — used by
   * LoginScreen / FirstRunSetupScreen. Defaults to `'light'`.
   */
  surface?: 'light' | 'dark' | undefined;
}

/**
 * Shared scaffolding for a labelled form control.
 *
 * Renders the column field wrapper, the `<label>`, and — when `error` is set —
 * the `role="alert"` error message, and passes the `aria-invalid` /
 * `aria-describedby` wiring to the control via render-prop children. Input,
 * TextArea, and SearchField consume it instead of each re-declaring an
 * identical wrapper, label, and error block.
 *
 * App-agnostic — a generic form primitive.
 */
export function FormField({
  id,
  label,
  error,
  children,
  className,
  surface = 'light',
}: FormFieldProps): React.ReactElement {
  const hasError = error !== undefined && error !== '';
  const errorId = hasError ? `${id}-error` : undefined;
  const isDark = surface === 'dark';

  return (
    <div className={cn(styles['field'], isDark && styles['field-dark'], className)}>
      {label !== undefined && (
        <label htmlFor={id} className={cn(styles['label'], isDark && styles['label-dark'])}>
          {label}
        </label>
      )}
      {children({ hasError, errorId })}
      {hasError && (
        <span id={errorId} className={styles['error-message']} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
