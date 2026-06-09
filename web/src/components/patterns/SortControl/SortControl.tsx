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
  /** The available sort options. */
  options: ReadonlyArray<SortOption<T>>;
  /** The currently selected value (controlled). */
  value: T;
  /** Called with the chosen value when the user picks a menu item. */
  onChange: (value: T) => void;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * Inline labelled sort dropdown.
 *
 * A bordered surface pill — `{label}: {selected} ▾` — that opens a small
 * radio menu beneath it. Implements the ARIA menu pattern: the trigger is a
 * `<button>` with `aria-haspopup="menu"` + `aria-expanded`; the menu is a
 * `role="menu"` of `role="menuitemradio"` items carrying `aria-checked`.
 *
 * The menu closes on selection, on `Escape`, and on a pointer-down outside
 * the control. Picking an item calls `onChange` (even when the same value is
 * re-picked — the parent may treat that as a no-op).
 *
 * Domain-free and generic over the value type `T`. Tier: components/patterns
 * (CODE_GUIDELINES §12.3). Allowed deps: the Icon primitive, lib/.
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

  const selected = options.find((o) => o.value === value);
  const selectedLabel = selected?.label ?? '';
  const menuId = `${id}-menu`;

  // Close on a pointer-down outside the control, and on Escape. Bound only
  // while the menu is open so there is no idle global listener.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    function onPointerDown(event: PointerEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [isOpen]);

  function pick(optionValue: T): void {
    onChange(optionValue);
    setIsOpen(false);
  }

  return (
    <div ref={rootRef} className={cn(styles['sort-control'], className)}>
      <button
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
        <ul id={menuId} role="menu" aria-label={label} className={styles['menu']}>
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <li key={option.value} role="none">
                <button
                  type="button"
                  role="menuitemradio"
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
