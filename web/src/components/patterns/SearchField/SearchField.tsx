import React, { useId, useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { cn } from '../../../lib/cn';
import styles from './SearchField.module.css';

export interface SearchFieldProps {
  /** Id for the underlying input — required for label association. */
  id: string;
  /** Visible label text rendered above the field. Omit to label externally. */
  label?: string;
  /** Placeholder hint inside the field. */
  placeholder?: string;
  /** Controlled value. Supply alongside onChange for controlled usage. */
  value?: string;
  /** Whether the field and submit button are non-interactive. */
  disabled?: boolean;
  /** Change handler for controlled usage. */
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  /**
   * Called with the current query string when the user submits.
   * Fires on Enter keypress and on submit button click.
   * Does NOT fire when the value is empty.
   */
  onSubmit: (query: string) => void;
  /** Additional class names to merge onto the root wrapper. */
  className?: string;
}

/**
 * Primary search-input pattern for the application.
 *
 * Styled using the Apple search-input style from DESIGN.md §4 — rounded field
 * with --radius-comfortable (11 px), a leading search icon, and an accessible
 * submit button. Composes the Icon and IconButton primitives.
 *
 * Fires onSubmit(value) on Enter keypress and on submit button click.
 * An empty value does not trigger a submission.
 */
export function SearchField({
  id,
  label,
  placeholder,
  value,
  disabled = false,
  onChange,
  onSubmit,
  className,
}: SearchFieldProps): React.ReactElement {
  // Internal state for uncontrolled usage. When `value` is provided (controlled),
  // this state is ignored and the controlled value drives the input.
  const [internalValue, setInternalValue] = useState('');

  // Use a ref to always read the latest value at submit time — avoids stale
  // closure inside the submit handler without needing to track every change.
  const inputRef = useRef<HTMLInputElement>(null);

  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : internalValue;

  // Auto-generate an id for the label association when not passed a stable one.
  // In practice the caller always passes id, but the hook makes the code safe.
  const autoId = useId();
  const inputId = id ?? autoId;

  function handleChange(event: React.ChangeEvent<HTMLInputElement>): void {
    if (!isControlled) {
      setInternalValue(event.target.value);
    }
    onChange?.(event);
  }

  function submit(): void {
    const val = inputRef.current?.value ?? currentValue;
    if (val.trim() === '') return;
    onSubmit(val);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      submit();
    }
  }

  const wrapperClasses = cn(styles['search-field'], className);

  return (
    <div className={wrapperClasses}>
      {label !== undefined && (
        <label htmlFor={inputId} className={styles['label']}>
          {label}
        </label>
      )}
      <div className={styles['input-wrapper']}>
        {/* Leading decorative search icon — aria-hidden, communicates intent visually */}
        <span className={styles['leading-icon']} aria-hidden="true">
          <Icon name="search" size="small" />
        </span>
        <input
          ref={inputRef}
          id={inputId}
          type="search"
          role="searchbox"
          placeholder={placeholder}
          value={currentValue}
          disabled={disabled}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          className={styles['input']}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
        />
        <span className={styles['trailing-button']}>
          <IconButton
            label="Search"
            type="button"
            disabled={disabled}
            onClick={submit}
          >
            <Icon name="search" size="small" />
          </IconButton>
        </span>
      </div>
    </div>
  );
}
