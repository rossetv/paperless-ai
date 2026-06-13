import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SettingsListField.module.css';

export interface SettingsListFieldProps {
  /** Element id — the settings Row associates its label with this via htmlFor. */
  id: string;
  /** Accessible name. Set as aria-label on the add input; the visible label is on the Row. */
  label: string;
  /** The current list of values. Controlled. */
  value: string[];
  /** Called with the updated array whenever an item is added, removed, or reordered. */
  onChange: (next: string[]) => void;
  /** Placeholder for the add-item input. */
  placeholder?: string;
  /** When true the field is shown but cannot be edited. */
  disabled?: boolean;
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/**
 * A pill-list field for the Settings screen.
 *
 * Renders each item as a numbered pill with a remove button. Below the pills,
 * an inline input lets the user type a new entry (confirmed via Enter or the
 * "Add" button). Up/down arrow buttons on each pill reorder the list.
 *
 * Follows the same label/id contract as {@link SettingsTextField}: the visible
 * label lives on the enclosing `Row`; this component exposes `aria-label` only.
 *
 * Tier: components/primitives. Allowed deps: lib/, styles/.
 */
export function SettingsListField({
  id,
  label,
  value,
  onChange,
  placeholder = 'Add a value…',
  disabled = false,
  className,
}: SettingsListFieldProps): React.ReactElement {
  const [draft, setDraft] = React.useState('');

  function addItem(): void {
    const trimmed = draft.trim();
    if (trimmed === '' || disabled) return;
    onChange([...value, trimmed]);
    setDraft('');
  }

  function removeItem(index: number): void {
    if (disabled) return;
    onChange(value.filter((_, i) => i !== index));
  }

  function moveItem(index: number, direction: -1 | 1): void {
    if (disabled) return;
    const next = [...value];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!];
    onChange(next);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      addItem();
    }
  }

  return (
    <div className={cn(styles['wrapper'], className)}>
      {value.length > 0 && (
        <ol className={styles['pill-list']} aria-label={`${label} items`}>
          {value.map((item, index) => (
            // key={item} not key={index}: the list is reorderable, so
            // positional keys cause React to mis-associate DOM/state on swap.
            // Duplicates are not supported by this field — each entry is a
            // distinct string value, making the item itself a stable key.
            <li key={item} className={styles['pill']}>
              <span className={styles['pill-number']}>{index + 1}</span>
              <span className={styles['pill-text']}>{item}</span>
              <div className={styles['pill-actions']}>
                <button
                  type="button"
                  className={styles['order-button']}
                  aria-label={`Move ${item} up`}
                  disabled={disabled || index === 0}
                  onClick={() => moveItem(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className={styles['order-button']}
                  aria-label={`Move ${item} down`}
                  disabled={disabled || index === value.length - 1}
                  onClick={() => moveItem(index, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className={styles['remove-button']}
                  aria-label={`Remove ${item}`}
                  disabled={disabled}
                  onClick={() => removeItem(index)}
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className={styles['add-row']}>
        <input
          id={id}
          type="text"
          aria-label={label}
          value={draft}
          placeholder={placeholder}
          disabled={disabled}
          spellCheck={false}
          className={styles['add-input']}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className={styles['add-button']}
          disabled={disabled || draft.trim() === ''}
          onClick={addItem}
        >
          Add
        </button>
      </div>
    </div>
  );
}
