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
  name?: string;
  value?: string;
  placeholder?: string;
  disabled?: boolean;
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
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  onFocus?: React.FocusEventHandler<HTMLInputElement>;
  onBlur?: React.FocusEventHandler<HTMLInputElement>;
  className?: string;
}

/** Labelled text input built on the shared `FormField` scaffolding. */
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
