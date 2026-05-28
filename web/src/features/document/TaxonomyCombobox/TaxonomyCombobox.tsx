/**
 * TaxonomyCombobox — searchable single-select with create-new option.
 *
 * Reused by the correspondent and document-type fields on the document page.
 * Closed state shows a trigger button with the selected item's name (or "—"
 * when nothing is selected). Open state renders a filtered text input plus a
 * listbox of matching options. When the query does not exactly match any
 * existing item, a "Create <query>" row is appended.
 *
 * Keyboard: Escape closes without firing onSelect or onCreate.
 * Arrow-key navigation is out of scope for v1 — the user clicks.
 *
 * canEdit=false renders the selected item's name as static text; no button,
 * no chevron, no interaction.
 */
import React from 'react';
import type { TaxonomyItem } from '../../../api/types';
import styles from './TaxonomyCombobox.module.css';

export interface TaxonomyComboboxProps {
  /** Column label shown to the left of the combobox. */
  label: string;
  /** Full list of available items. */
  items: TaxonomyItem[];
  /** ID of the currently selected item, or null if nothing is selected. */
  selectedId: number | null;
  /** Whether the field can be opened and edited. */
  canEdit: boolean;
  /**
   * Called with the selected item's ID when the user picks an existing option,
   * or with `null` when the user clicks the "Clear" option to remove the
   * current selection.
   */
  onSelect: (id: number | null) => void;
  /** Called with the trimmed query string when the user clicks "Create <query>". */
  onCreate: (name: string) => void;
}

export function TaxonomyCombobox({
  label, items, selectedId, canEdit, onSelect, onCreate,
}: TaxonomyComboboxProps): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const selected = items.find((i) => i.id === selectedId) ?? null;

  // ── Read-only mode ──────────────────────────────────────────────────────────
  if (!canEdit) {
    return (
      <div className={styles['row']}>
        <div className={styles['label']}>{label}</div>
        <div className={styles['value']}>{selected?.name ?? '—'}</div>
      </div>
    );
  }

  const q = query.trim().toLowerCase();
  const filtered = items.filter((i) => i.name.toLowerCase().includes(q));
  const exactMatch = items.some((i) => i.name.toLowerCase() === q);

  function close(): void {
    setOpen(false);
    setQuery('');
  }

  // ── Closed state ────────────────────────────────────────────────────────────
  if (!open) {
    return (
      <div className={styles['row']}>
        <div className={styles['label']}>{label}</div>
        <div className={styles['cell']}>
          <button
            type="button"
            className={styles['trigger']}
            onClick={() => setOpen(true)}
          >
            {selected?.name ?? '—'}
            <span className={styles['chevron']} aria-hidden="true">▾</span>
          </button>
        </div>
      </div>
    );
  }

  // ── Open state ──────────────────────────────────────────────────────────────
  return (
    <div className={styles['row']}>
      <div className={styles['label']}>{label}</div>
      <div className={styles['cell']}>
        <input
          role="combobox"
          aria-expanded
          autoFocus
          className={styles['input']}
          value={query}
          placeholder="Type to search…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') close(); }}
        />
        <ul role="listbox" className={styles['list']}>
          {selectedId !== null && (
            <li
              role="option"
              aria-selected={false}
              className={styles['clear']}
              onClick={() => { onSelect(null); close(); }}
            >
              Clear
            </li>
          )}
          {filtered.map((i) => (
            <li
              key={i.id}
              role="option"
              aria-selected={i.id === selectedId}
              className={styles['opt']}
              onClick={() => { onSelect(i.id); close(); }}
            >
              {i.name}
              <small>{i.document_count} docs</small>
            </li>
          ))}
          {q !== '' && !exactMatch && (
            <li
              role="option"
              className={styles['create']}
              onClick={() => { onCreate(query.trim()); close(); }}
            >
              Create "{query.trim()}"
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
