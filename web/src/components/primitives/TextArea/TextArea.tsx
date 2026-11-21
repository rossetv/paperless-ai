import React from 'react';
import { cn } from '../../../lib/cn';
import { FormField } from '../FormField/FormField';
import styles from './TextArea.module.css';

export interface TextAreaProps {
  /** The id — required for label association and accessible forms. */
  id: string;
  /** Visible label text rendered in a <label> element. Omit to label externally. */
  label?: string;
  name?: string;
  value?: string;
  placeholder?: string;
  /** Number of visible text rows. Defaults to 4. */
  rows?: number;
  disabled?: boolean;
  required?: boolean;
  /** Validation error message — also sets aria-invalid. */
  error?: string;
  onChange?: React.ChangeEventHandler<HTMLTextAreaElement>;
  onFocus?: React.FocusEventHandler<HTMLTextAreaElement>;
  onBlur?: React.FocusEventHandler<HTMLTextAreaElement>;
  className?: string;
}

/** Labelled multi-line text input built on the shared `FormField` scaffolding. */
export function TextArea({
  id,
  label,
  name,
  value,
  placeholder,
  rows = 4,
  disabled = false,
  required = false,
  error,
  onChange,
  onFocus,
  onBlur,
  className,
}: TextAreaProps): React.ReactElement {
  return (
    <FormField id={id} label={label} error={error} className={className}>
      {({ hasError, errorId }) => (
        <textarea
          id={id}
          name={name}
          value={value}
          placeholder={placeholder}
          rows={rows}
          disabled={disabled}
          required={required}
          aria-invalid={hasError ? 'true' : undefined}
          aria-describedby={errorId}
          onChange={onChange}
          onFocus={onFocus}
          onBlur={onBlur}
          className={cn(styles['textarea'], hasError && styles['textarea-error'])}
        />
      )}
    </FormField>
  );
}
