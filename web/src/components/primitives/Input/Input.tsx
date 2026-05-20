import stylesRaw from './Input.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

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
  error?: string;
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
 * Validation errors appear below the input and set aria-invalid for
 * assistive technology.
 *
 * Styled as the Filter/Search button style from DESIGN.md §4 — 11px radius,
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
}: InputProps): React.ReactElement {
  const hasError = error !== undefined && error !== '';
  const errorId = hasError ? `${id}-error` : undefined;

  const wrapperClasses = [styles['wrapper'], className].filter(Boolean).join(' ');

  return (
    <div className={wrapperClasses}>
      {label !== undefined && (
        <label htmlFor={id} className={styles['label']}>
          {label}
        </label>
      )}
      <input
        id={id}
        type={type}
        name={name}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        aria-invalid={hasError ? 'true' : undefined}
        aria-describedby={errorId}
        onChange={onChange}
        onFocus={onFocus}
        onBlur={onBlur}
        className={[styles['input'], hasError ? styles['input-error'] : undefined]
          .filter(Boolean)
          .join(' ')}
      />
      {hasError && (
        <span id={errorId} className={styles['error-message']} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
