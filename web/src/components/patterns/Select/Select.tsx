import React, { useEffect, useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './Select.module.css';

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
  options: ReadonlyArray<SelectOption<T>>;
  /** Currently selected value (controlled). */
  value?: T;
  /** Text shown when no option is selected. */
  placeholder?: string;
  disabled?: boolean;
  /** Called with the new value when the user selects an option. */
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Accessible custom dropdown implementing the ARIA combobox-with-listbox pattern.
 *
 * Enter, Space or ArrowDown on the trigger opens the list; ArrowUp/Down move the
 * highlight, Enter selects and Escape closes without selecting.
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

  const listboxId = `${id}-listbox`;
  const optionId = (index: number): string => `${id}-option-${index}`;

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Set when the pointer moved the highlight, so the list is not scrolled under it.
  const pointerMoved = useRef(false);

  // Close on outside pointer-down (bound only while open).
  // This also ensures a second dropdown opening dismisses this one, because
  // clicking the other dropdown trigger is an outside-pointer-down for this root.
  useEffect(() => {
    if (!isOpen) return;
    function onPointerDown(event: PointerEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setHighlightedIndex(-1);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [isOpen]);

  // Keep the keyboard-highlighted option visible in a long, scrolling list.
  useEffect(() => {
    if (!isOpen || highlightedIndex < 0) return;
    if (pointerMoved.current) {
      pointerMoved.current = false;
      return;
    }
    const el = document.getElementById(optionId(highlightedIndex));
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- optionId only depends on id
  }, [isOpen, highlightedIndex]);

  const selectedOption = options.find((o) => o.value === value);
  const displayLabel = selectedOption?.label ?? placeholder;

  function open(initialHighlight?: number): void {
    if (disabled) return;
    pointerMoved.current = false;
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
    pointerMoved.current = false;
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
        } else {
          const highlighted = options[highlightedIndex >= 0 ? highlightedIndex : 0];
          if (highlighted !== undefined) {
            selectOption(highlighted.value);
          }
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
      case 'Home':
      case 'End':
        if (isOpen) {
          event.preventDefault();
          setHighlightedIndex(event.key === 'Home' ? 0 : options.length - 1);
        }
        break;
      case 'Escape':
        if (isOpen) {
          // Handled here, so a dialog around the list must not also close.
          event.preventDefault();
          event.stopPropagation();
          close();
        }
        break;
      default:
        break;
    }
  }

  const wrapperClasses = cn(styles['select'], className);

  return (
    <div
      ref={rootRef}
      className={wrapperClasses}
      onBlur={(event) => {
        // Focus left the control (Tab, programmatic): close without picking or refocusing.
        if (isOpen && !rootRef.current?.contains(event.relatedTarget)) {
          setIsOpen(false);
          setHighlightedIndex(-1);
        }
      }}
    >
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
        aria-activedescendant={
          isOpen && highlightedIndex >= 0
            ? optionId(highlightedIndex)
            : undefined
        }
        disabled={disabled}
        className={cn(styles['trigger'], isOpen ? styles['open'] : undefined)}
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
          // A scrolling box is a Tab stop in browsers; focus must stay on the trigger.
          tabIndex={-1}
          // Keeps focus on the trigger so clicking an option or the scrollbar is not a blur.
          onMouseDown={(e) => e.preventDefault()}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isHighlighted = index === highlightedIndex;
            return (
              <li
                key={option.value}
                id={optionId(index)}
                role="option"
                aria-selected={isSelected}
                className={cn(
                  styles['option'],
                  isSelected ? styles['selected'] : undefined,
                  isHighlighted ? styles['highlighted'] : undefined,
                )}
                onClick={() => selectOption(option.value)}
                // Not mouseenter: a keyboard scroll moves rows under a resting pointer.
                onMouseMove={() => {
                  if (index === highlightedIndex) return;
                  pointerMoved.current = true;
                  setHighlightedIndex(index);
                }}
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
