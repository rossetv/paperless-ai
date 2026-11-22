import React, { useEffect, useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './SortControl.module.css';

/** One option in the sort menu. */
export interface SortOption<T extends string = string> {
  /** The machine value passed to `onChange`. */
  value: T;
  /** The human-readable label shown in the menu and on the trigger. */
  label: string;
}

export interface SortControlProps<T extends string = string> {
  /** Id for the trigger button — used to associate the menu. */
  id: string;
  /** The muted prefix label on the trigger, e.g. "Sort". */
  label: string;
  options: ReadonlyArray<SortOption<T>>;
  /** The currently selected value (controlled). */
  value: T;
  /** Called with the chosen value when the user picks a menu item. */
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Inline labelled sort dropdown (`{label}: {selected} ▾`) using the ARIA menu
 * pattern with `menuitemradio` items.
 *
 * Focus moves into the menu on open; Arrow Up/Down (wrapping), Home and End move
 * between items, and Escape or a pick returns focus to the trigger. Also closes on
 * Tab or an outside pointer-down. Re-picking the current
 * value still calls `onChange`.
 */
export function SortControl<T extends string = string>({
  id,
  label,
  options,
  value,
  onChange,
  className,
}: SortControlProps<T>): React.ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const selected = options.find((o) => o.value === value);
  const selectedLabel = selected?.label ?? '';
  const menuId = `${id}-menu`;

  // Close on a pointer-down outside the control. Bound only while the menu is
  // open so there is no idle global listener.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    function onPointerDown(event: PointerEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [isOpen]);

  // Move focus into the menu on open, onto the checked item.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const items = menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]');
    const checked = menuRef.current?.querySelector<HTMLElement>('[aria-checked="true"]');
    (checked ?? items?.[0])?.focus();
  }, [isOpen]);

  function onKeyDown(event: React.KeyboardEvent): void {
    if (!isOpen) {
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === 'Tab') {
      // Focus the trigger before the menu unmounts so the browser's Tab moves on from it.
      triggerRef.current?.focus();
      setIsOpen(false);
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [],
    );
    const current = items.indexOf(document.activeElement as HTMLElement);
    if (items.length === 0 || current === -1) {
      return;
    }
    let next: number;
    if (event.key === 'ArrowDown') {
      next = (current + 1) % items.length;
    } else if (event.key === 'ArrowUp') {
      next = (current - 1 + items.length) % items.length;
    } else if (event.key === 'Home') {
      next = 0;
    } else if (event.key === 'End') {
      next = items.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    items[next]?.focus();
  }

  function pick(optionValue: T): void {
    onChange(optionValue);
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div
      ref={rootRef}
      className={cn(styles['sort-control'], className)}
      onKeyDown={onKeyDown}
    >
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className={styles['trigger']}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <span className={styles['label']}>{label}</span>
        <span className={styles['value']}>{selectedLabel}</span>
        <span
          className={cn(styles['chevron'], isOpen && styles['chevron-open'])}
          aria-hidden="true"
        >
          <Icon name="chevron-down" size="small" />
        </span>
      </button>

      {isOpen && (
        <ul
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          tabIndex={-1}
          className={styles['menu']}
        >
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <li key={option.value} role="none">
                <button
                  type="button"
                  role="menuitemradio"
                  tabIndex={-1}
                  aria-checked={isSelected}
                  className={cn(
                    styles['item'],
                    isSelected && styles['item-selected'],
                  )}
                  onClick={() => pick(option.value)}
                >
                  {option.label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
