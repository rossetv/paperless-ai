import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './FilterableListbox.module.css';

/** A single selectable item in the listbox. */
export interface FilterableItem<T extends string | number = string> {
  /** The machine value passed to `onSelect`. */
  value: T;
  /** The human-readable label — also the string filtered against. */
  label: string;
  /** Optional muted trailing meta text (e.g. "12 docs"). */
  meta?: string;
}

export interface FilterableListboxProps<T extends string | number = string> {
  /** Id root for ARIA associations (input, listbox, option ids derive from it). */
  id: string;
  /** The full set of selectable items (the caller pre-filters out anything it does not want offered, e.g. already-selected tags in multi-select). */
  items: ReadonlyArray<FilterableItem<T>>;
  /**
   * The current selection used to mark options `aria-selected`. A single value
   * (or `null`) in single-select mode; an array of values in multi-select mode.
   */
  value: T | null | ReadonlyArray<T>;
  /** Called with the chosen item's value when the user picks an option. */
  onSelect: (value: T) => void;
  /**
   * Called with the trimmed query when the user activates the "Create …" row.
   * Omit to disable the create-new affordance entirely.
   */
  onCreate?: ((query: string) => void) | undefined;
  /** Placeholder for the filter input. */
  placeholder?: string | undefined;
  /**
   * Multi-select mode keeps the listbox open after a pick (the caller is
   * expected to remove the picked item from `items` on the next render) and
   * accepts an array `value`. Single-select mode closes on pick. Default false.
   */
  multiple?: boolean | undefined;
  /**
   * Label shown on the closed trigger when nothing is selected. In single-select
   * this is the empty placeholder (e.g. "—"); in multi-select the "add" affordance
   * (e.g. "+ Add tag"). Required so the trigger always has an accessible name.
   */
  triggerLabel: string;
  /**
   * In single-select, the label of the currently-selected item to show on the
   * closed trigger. Ignored in multi-select (the caller renders chips itself).
   */
  selectedLabel?: string | undefined;
  /**
   * Optional row rendered at the top of the open list (e.g. a "Clear" action in
   * single-select). It is a real focusable-by-activedescendant option.
   */
  clearOption?: { label: string; onClear: () => void } | undefined;
  /** Additional class names merged onto the root. */
  className?: string | undefined;
}

/**
 * Filtered, keyboard-navigable single- or multi-select ARIA combobox with an
 * optional create-new row. Backs `TaxonomyCombobox` (single-select) and
 * `TagEditor` (multi-select) — see DESIGN.md §11.5 / DD-5.
 *
 * Closed, it renders a trigger button. Open, it renders a `role="combobox"`
 * filter input (`aria-expanded`, `aria-controls`, `aria-activedescendant`) above
 * a `role="listbox"` of `role="option"` rows. The full option set, in order, is:
 *   [ clear row ]  [ filtered items ]  [ "Create <query>" row ]
 * Each carries a synthetic activedescendant id so the highlight is announced.
 *
 * Keyboard:
 *  - ArrowDown / ArrowUp — move the highlight (wraps within the visible set).
 *  - Enter — activate the highlighted row (select / clear / create).
 *  - Escape — close without firing any callback; focus returns to the trigger.
 * The list also closes on a pointer-down outside the root (mirrors
 * SortControl / UserMenu). Domain-free; generic over the item value type `T`.
 * Tier: components/patterns (allowed deps: Icon primitive, lib/).
 */
export function FilterableListbox<T extends string | number = string>({
  id,
  items,
  value,
  onSelect,
  onCreate,
  placeholder = 'Type to search…',
  multiple = false,
  triggerLabel,
  selectedLabel,
  clearOption,
  className,
}: FilterableListboxProps<T>): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // Index into the flat row list (-1 = nothing highlighted).
  const [highlight, setHighlight] = useState(-1);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Unique suffix so two instances sharing the same `id` prop never collide on
  // the generated option/listbox ids.
  const uid = useId();
  const listboxId = `${id}-listbox-${uid}`;
  const optionId = (key: string): string => `${id}-option-${key}-${uid}`;

  const selectedValues = useMemo<ReadonlyArray<T>>(() => {
    if (value === null || value === undefined) return [];
    return Array.isArray(value) ? value : [value as T];
  }, [value]);

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => items.filter((item) => item.label.toLowerCase().includes(q)),
    [items, q],
  );
  // Suppress the create row when the query exactly matches an offered item's
  // label (case-insensitive) — creating a duplicate makes no sense.
  const exactMatch = useMemo(
    () => items.some((item) => item.label.toLowerCase() === q),
    [items, q],
  );
  const showCreate = onCreate !== undefined && q !== '' && !exactMatch;

  // The flat, ordered row model the keyboard navigates and the markup renders.
  // Kept in one place so highlight indices, rendering, and Enter all agree.
  type Row =
    | { kind: 'clear' }
    | { kind: 'item'; item: FilterableItem<T> }
    | { kind: 'create' };
  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    if (clearOption !== undefined) out.push({ kind: 'clear' });
    for (const item of filtered) out.push({ kind: 'item', item });
    if (showCreate) out.push({ kind: 'create' });
    return out;
  }, [clearOption, filtered, showCreate]);

  // Keep the highlight in range as the filtered set shrinks/grows.
  useEffect(() => {
    setHighlight((prev) => (prev >= rows.length ? rows.length - 1 : prev));
  }, [rows.length]);

  // Close on outside pointer-down and on Escape — bound only while open.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
        setQuery('');
        setHighlight(-1);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  function openList(): void {
    setOpen(true);
    setHighlight(-1);
  }

  function close(restoreFocus: boolean): void {
    setOpen(false);
    setQuery('');
    setHighlight(-1);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function activateRow(row: Row): void {
    switch (row.kind) {
      case 'clear':
        clearOption?.onClear();
        close(true);
        break;
      case 'item':
        onSelect(row.item.value);
        if (multiple) {
          // Stay open for the next pick; clear the query so the freshly-removed
          // item's neighbours are easy to reach.
          setQuery('');
          setHighlight(-1);
          inputRef.current?.focus();
        } else {
          close(true);
        }
        break;
      case 'create':
        onCreate?.(query.trim());
        close(true);
        break;
    }
  }

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (rows.length === 0) return;
        setHighlight((prev) => (prev + 1 >= rows.length ? 0 : prev + 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (rows.length === 0) return;
        setHighlight((prev) => (prev <= 0 ? rows.length - 1 : prev - 1));
        break;
      case 'Enter': {
        event.preventDefault();
        if (highlight >= 0 && highlight < rows.length) {
          const activeRow = rows[highlight];
          if (activeRow !== undefined) activateRow(activeRow);
        }
        break;
      }
      case 'Escape':
        event.preventDefault();
        close(true);
        break;
      default:
        break;
    }
  }

  const activeDescendant = ((): string | undefined => {
    if (!open || highlight < 0 || highlight >= rows.length) return undefined;
    const row = rows[highlight];
    if (row === undefined) return undefined;
    if (row.kind === 'clear') return optionId('clear');
    if (row.kind === 'create') return optionId('create');
    return optionId(String(row.item.value));
  })();

  return (
    <div ref={rootRef} className={cn(styles['root'], className)}>
      {!open ? (
        <button
          ref={triggerRef}
          id={id}
          type="button"
          className={styles['trigger']}
          aria-haspopup="listbox"
          aria-expanded={false}
          onClick={openList}
        >
          <span className={styles['trigger-label']}>
            {selectedLabel ?? triggerLabel}
          </span>
          {!multiple && (
            <span className={styles['chevron']} aria-hidden="true">
              <Icon name="chevron-down" size="small" />
            </span>
          )}
        </button>
      ) : (
        <>
          <input
            ref={inputRef}
            id={id}
            autoFocus
            type="text"
            role="combobox"
            aria-expanded
            aria-controls={listboxId}
            aria-activedescendant={activeDescendant}
            aria-autocomplete="list"
            aria-label={triggerLabel}
            className={styles['input']}
            value={query}
            placeholder={placeholder}
            onChange={(e) => {
              setQuery(e.target.value);
              setHighlight(-1);
            }}
            onKeyDown={handleInputKeyDown}
          />
          <ul id={listboxId} role="listbox" className={styles['listbox']}>
            {rows.length === 0 && (
              <li className={styles['empty']} aria-disabled="true">
                No matches
              </li>
            )}
            {rows.map((row, index) => {
              const highlighted = index === highlight;
              if (row.kind === 'clear') {
                return (
                  <li
                    key="__clear"
                    id={optionId('clear')}
                    role="option"
                    aria-selected={false}
                    className={cn(
                      styles['option'],
                      styles['clear'],
                      highlighted && styles['highlighted'],
                    )}
                    // onMouseDown+preventDefault keeps the input focused so its
                    // blur does not race the click (see DD-5 / TagEditor note).
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => activateRow(row)}
                  >
                    {clearOption?.label}
                  </li>
                );
              }
              if (row.kind === 'create') {
                return (
                  <li
                    key="__create"
                    id={optionId('create')}
                    role="option"
                    aria-selected={false}
                    className={cn(
                      styles['option'],
                      styles['create'],
                      highlighted && styles['highlighted'],
                    )}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => activateRow(row)}
                  >
                    Create &ldquo;{query.trim()}&rdquo;
                  </li>
                );
              }
              const isSelected = selectedValues.includes(row.item.value);
              return (
                <li
                  key={row.item.value}
                  id={optionId(String(row.item.value))}
                  role="option"
                  aria-selected={isSelected}
                  className={cn(
                    styles['option'],
                    isSelected && styles['selected'],
                    highlighted && styles['highlighted'],
                  )}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => activateRow(row)}
                >
                  <span className={styles['option-label']}>{row.item.label}</span>
                  {row.item.meta !== undefined && (
                    <small className={styles['option-meta']}>{row.item.meta}</small>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
