import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './FormField.module.css';

/** The aria wiring a `FormField` hands to its control. */
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
  className?: string | undefined;
  /**
   * `'dark'` switches the label and control to the forced-dark island tokens, as
   * on the login and first-run setup screens. Defaults to `'light'`.
   */
  surface?: 'light' | 'dark' | undefined;
}

/**
 * Labelled form-control scaffolding: the field wrapper, the `<label>` and, when
 * `error` is set, a `role="alert"` message. The aria wiring reaches the control
 * through render-prop children.
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
