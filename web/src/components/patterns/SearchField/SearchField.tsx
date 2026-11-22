import React, { useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { FormField } from '../../primitives/FormField/FormField';
import { cn } from '../../../lib/cn';
import styles from './SearchField.module.css';

export interface SearchFieldProps {
  /** Id for the underlying input — required for label association. */
  id: string;
  /** Visible label text rendered above the field. Omit to label externally. */
  label?: string;
  /** Accessible name when there is no visible label and no placeholder to name the field. */
  ariaLabel?: string;
  placeholder?: string;
  /** Controlled value. Supply alongside onChange for controlled usage. */
  value?: string;
  /**
   * Initial value for uncontrolled usage — the field is editable and
   * pre-filled with this text. Ignored when `value` (controlled) is set.
   */
  defaultValue?: string;
  disabled?: boolean;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  /**
   * Called with the current query string when the user submits.
   * Fires on Enter keypress and on submit button click.
   * Does NOT fire when the value is empty, unless `allowEmpty` is set.
   */
  onSubmit: (query: string) => void;
  /** Let an empty submit through, so a caller can clear what the field filters. */
  allowEmpty?: boolean;
  className?: string;
}

/**
 * Search input with a leading icon and a submit button. Calls `onSubmit` on Enter
 * or a submit click, never with an empty value unless `allowEmpty`.
 */
export function SearchField({
  id,
  label,
  ariaLabel,
  placeholder,
  value,
  defaultValue = '',
  disabled = false,
  onChange,
  onSubmit,
  allowEmpty = false,
  className,
}: SearchFieldProps): React.ReactElement {
  // Uncontrolled state, seeded from `defaultValue`; ignored when `value` is set.
  const [internalValue, setInternalValue] = useState(defaultValue);

  // Use a ref to always read the latest value at submit time — avoids stale
  // closure inside the submit handler without needing to track every change.
  const inputRef = useRef<HTMLInputElement>(null);

  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : internalValue;

  const inputId = id;

  function handleChange(event: React.ChangeEvent<HTMLInputElement>): void {
    if (!isControlled) {
      setInternalValue(event.target.value);
    }
    onChange?.(event);
  }

  function submit(): void {
    const val = inputRef.current?.value ?? currentValue;
    if (!allowEmpty && val.trim() === '') return;
    onSubmit(val);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      submit();
    }
  }

  return (
    <FormField id={inputId} label={label} className={cn(styles['search-field'], className)}>
      {() => (
        <div className={styles['input-wrapper']}>
          <span className={styles['leading-icon']} aria-hidden="true">
            <Icon name="search" size="small" />
          </span>
          <input
            ref={inputRef}
            id={inputId}
            type="search"
            role="searchbox"
            aria-label={ariaLabel}
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
              className={cn(styles['submit-button'])}
            >
              <Icon name="search" size="small" />
            </IconButton>
          </span>
        </div>
      )}
    </FormField>
  );
}
