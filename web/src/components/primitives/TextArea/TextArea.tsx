import { cn } from '../../../lib/cn';
import styles from './TextArea.module.css';

export interface TextAreaProps {
  /** The id — required for label association and accessible forms. */
  id: string;
  /** Visible label text rendered in a <label> element. Omit to label externally. */
  label?: string;
  /** Input name attribute for form submission. */
  name?: string;
  /** Controlled value. */
  value?: string;
  /** Placeholder hint. */
  placeholder?: string;
  /** Number of visible text rows. Defaults to 4. */
  rows?: number;
  /** Whether the textarea is non-interactive. */
  disabled?: boolean;
  /** Whether the textarea is required. */
  required?: boolean;
  /** Validation error message — also sets aria-invalid. */
  error?: string;
  /** Change handler for controlled usage. */
  onChange?: React.ChangeEventHandler<HTMLTextAreaElement>;
  /** Focus handler. */
  onFocus?: React.FocusEventHandler<HTMLTextAreaElement>;
  /** Blur handler. */
  onBlur?: React.FocusEventHandler<HTMLTextAreaElement>;
  /** Additional class names for the root wrapper. */
  className?: string;
}

/**
 * Generic multi-line text input primitive.
 *
 * Mirrors the structure of the Input primitive: <label> + <textarea> pair,
 * correctly associated via the `id` prop, with error display and aria-invalid.
 *
 * Design tokens drive all visual values — no hardcoded sizes or colours.
 */
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
  const hasError = error !== undefined && error !== '';
  const errorId = hasError ? `${id}-error` : undefined;

  const wrapperClasses = cn(styles['wrapper'], className);

  return (
    <div className={wrapperClasses}>
      {label !== undefined && (
        <label htmlFor={id} className={styles['label']}>
          {label}
        </label>
      )}
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
        className={cn(styles['textarea'], hasError ? styles['textarea-error'] : undefined)}
      />
      {hasError && (
        <span id={errorId} className={styles['error-message']} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
