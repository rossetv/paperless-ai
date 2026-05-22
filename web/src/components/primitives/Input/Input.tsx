import React from 'react';
import { cn } from '../../../lib/cn';
import { FormField } from '../FormField/FormField';
import styles from './Input.module.css';

export interface InputProps {
  /** The id — required for label association and accessible forms. */
  id: string;
  /** Visible label text rendered in a <label> element. Omit to label externally. */
  label?: string;
  /** Input type — defaults to 'text'. */
  type?: 'text' | 'email' | 'password' | 'search' | 'tel' | 'url' | 'number' | 'date';
  /** Input name attribute for form submission. */
  name?: string;
  /** Controlled value. */
  value?: string;
  /** Placeholder hint. */
  placeholder?: string;
  /** Whether the input is non-interactive. */
  disabled?: boolean;
  /** Whether the input is required. */
  required?: boolean;
  /** Validation error message — also sets aria-invalid. */
  error?: string | undefined;
  /**
   * Surface the input is rendered on. `'dark'` switches the control and its
   * label to the forced-dark island tokens. Defaults to `'light'`.
   */
  surface?: 'light' | 'dark';
  /** Browser autofill hint — forwarded to the native `autocomplete` attribute. */
  autoComplete?: string;
  /** Change handler for controlled usage. */
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  /** Focus handler. */
  onFocus?: React.FocusEventHandler<HTMLInputElement>;
  /** Blur handler. */
  onBlur?: React.FocusEventHandler<HTMLInputElement>;
  /** Additional class names for the root wrapper. */
  className?: string;
}

/**
 * Generic text input primitive.
 *
 * Renders a <label> + <input> pair, correctly associated via the `id` prop.
 * The label, the field wrapper, and the validation-error region come from the
 * shared `FormField` scaffolding; this component only owns the <input> itself.
 *
 * Styled as the Filter/Search field style from DESIGN.md §4 — 11px radius,
 * light background, accent focus ring.
 */
export function Input({
  id,
  label,
  type = 'text',
  name,
  value,
  placeholder,
  disabled = false,
  required = false,
  error,
  onChange,
  onFocus,
  onBlur,
  className,
  surface = 'light',
  autoComplete,
}: InputProps): React.ReactElement {
  return (
    <FormField id={id} label={label} error={error} className={className} surface={surface}>
      {({ hasError, errorId }) => (
        <input
          id={id}
          type={type}
          name={name}
          autoComplete={autoComplete}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          aria-invalid={hasError ? 'true' : undefined}
          aria-describedby={errorId}
          onChange={onChange}
          onFocus={onFocus}
          onBlur={onBlur}
          className={cn(
            styles['input'],
            surface === 'dark' && styles['input-dark'],
            hasError && styles['input-error'],
          )}
        />
      )}
    </FormField>
  );
}
