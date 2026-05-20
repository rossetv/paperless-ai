import React, { useId, useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import stylesRaw from './Select.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/** A single option in the Select. */
export interface SelectOption<T extends string = string> {
  /** The machine value passed to onChange. */
  value: T;
  /** The human-readable label displayed in the list. */
  label: string;
}

export interface SelectProps<T extends string = string> {
  /** Id for ARIA associations. */
  id: string;
  /** Visible label rendered above the control. */
  label?: string;
  /** The available options. */
  options: Array<SelectOption<T>>;
  /** Currently selected value (controlled). */
  value?: T;
  /** Text shown when no option is selected. */
  placeholder?: string;
  /** Whether the control is non-interactive. */
  disabled?: boolean;
  /** Called with the new value when the user selects an option. */
  onChange: (value: T) => void;
  /** Additional class names to merge onto the root wrapper. */
  className?: string;
}

/**
 * Accessible custom dropdown select.
 *
 * Implements the ARIA combobox pattern with listbox:
 * - role="combobox" on the trigger button (aria-haspopup="listbox")
 * - role="listbox" on the dropdown container
 * - role="option" + aria-selected on each item
 *
 * Keyboard support:
 * - Click / Enter / Space / ArrowDown on the trigger — opens the list
 * - ArrowDown / ArrowUp — move the highlighted option
 * - Enter — selects the highlighted option
 * - Escape — closes without selecting
 *
 * Generic over the option value type T so callers get typed onChange callbacks.
 * App-agnostic — does not know about documents, facets, or search.
 */
export function Select<T extends string = string>({
  id,
  label,
  options,
  value,
  placeholder = 'Select…',
  disabled = false,
  onChange,
  className,
}: SelectProps<T>): React.ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  // Index into `options` that is currently keyboard-highlighted (-1 = none)
  const [highlightedIndex, setHighlightedIndex] = useState(-1);

  const autoId = useId();
  const listboxId = `${id ?? autoId}-listbox`;

  const triggerRef = useRef<HTMLButtonElement>(null);

  const selectedOption = options.find((o) => o.value === value);
  const displayLabel = selectedOption?.label ?? placeholder;

  function open(initialHighlight?: number): void {
    if (disabled) return;
    setIsOpen(true);
    // Pre-highlight the currently selected option so arrow keys start from there.
    // If an initial highlight index is supplied (e.g. ArrowDown → first item),
    // use it instead.
    if (initialHighlight !== undefined) {
      setHighlightedIndex(initialHighlight);
    } else {
      const selectedIndex =
        value !== undefined ? options.findIndex((o) => o.value === value) : -1;
      setHighlightedIndex(selectedIndex);
    }
  }

  function close(): void {
    setIsOpen(false);
    setHighlightedIndex(-1);
    triggerRef.current?.focus();
  }

  function selectOption(optionValue: T): void {
    onChange(optionValue);
    close();
  }

  function handleTriggerKeyDown(event: React.KeyboardEvent<HTMLButtonElement>): void {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (!isOpen) {
          // ArrowDown on a closed list: open it and highlight the first item (or
          // the selected item if one is already chosen).
          const downStart =
            value !== undefined ? Math.max(options.findIndex((o) => o.value === value), 0) : 0;
          open(downStart);
        } else {
          setHighlightedIndex((prev) => Math.min(prev + 1, options.length - 1));
        }
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        if (!isOpen) {
          open();
        } else if (highlightedIndex >= 0) {
          selectOption(options[highlightedIndex].value);
        }
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (!isOpen) {
          open();
        } else {
          setHighlightedIndex((prev) => Math.max(prev - 1, 0));
        }
        break;
      case 'Escape':
        if (isOpen) {
          event.preventDefault();
          close();
        }
        break;
      default:
        break;
    }
  }

  function handleListKeyDown(event: React.KeyboardEvent<HTMLUListElement>): void {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setHighlightedIndex((prev) => Math.min(prev + 1, options.length - 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setHighlightedIndex((prev) => Math.max(prev - 1, 0));
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        if (highlightedIndex >= 0) {
          selectOption(options[highlightedIndex].value);
        }
        break;
      case 'Escape':
        event.preventDefault();
        close();
        break;
      default:
        break;
    }
  }

  const wrapperClasses = [styles['select'], className].filter(Boolean).join(' ');

  return (
    <div className={wrapperClasses}>
      {label !== undefined && (
        <span id={`${id}-label`} className={styles['label']}>
          {label}
        </span>
      )}
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={listboxId}
        aria-labelledby={label !== undefined ? `${id}-label ${id}` : undefined}
        aria-label={label === undefined ? displayLabel : undefined}
        disabled={disabled}
        className={[styles['trigger'], isOpen ? styles['open'] : undefined]
          .filter(Boolean)
          .join(' ')}
        onClick={() => (isOpen ? close() : open())}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className={styles['trigger-label']}>{displayLabel}</span>
        <span className={styles['trigger-icon']} aria-hidden="true">
          <Icon name="chevron-down" size="small" />
        </span>
      </button>

      {isOpen && (
        <ul
          id={listboxId}
          role="listbox"
          aria-labelledby={label !== undefined ? `${id}-label` : undefined}
          className={styles['listbox']}
          onKeyDown={handleListKeyDown}
          tabIndex={-1}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isHighlighted = index === highlightedIndex;
            return (
              <li
                key={option.value}
                id={`${id}-option-${option.value}`}
                role="option"
                aria-selected={isSelected}
                className={[
                  styles['option'],
                  isSelected ? styles['selected'] : undefined,
                  isHighlighted ? styles['highlighted'] : undefined,
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => selectOption(option.value)}
                onMouseEnter={() => setHighlightedIndex(index)}
              >
                {option.label}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
