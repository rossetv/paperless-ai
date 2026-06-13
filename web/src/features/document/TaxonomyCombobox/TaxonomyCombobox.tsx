/**
 * TaxonomyCombobox — searchable single-select with create-new option.
 *
 * Reused by the correspondent and document-type fields on the document page.
 * Closed state shows a trigger button with the selected item's name (or "—"
 * when nothing is selected). Open state renders a filtered text input plus a
 * listbox of matching options, via the FilterableListbox primitive.
 *
 * canEdit=false renders the selected item's name as static text; no button,
 * no chevron, no interaction.
 */
import React, { useId } from 'react';
import type { TaxonomyItem } from '../../../api/types';
import { FilterableListbox } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import type { FilterableItem } from '../../../components/patterns/FilterableListbox/FilterableListbox';
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
  const uid = useId();
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

  const listboxItems: FilterableItem<number>[] = items.map((i) => ({
    value: i.id,
    label: i.name,
    meta: `${i.document_count} docs`,
  }));

  return (
    <div className={styles['row']}>
      <div className={styles['label']}>{label}</div>
      <div className={styles['cell']}>
        <FilterableListbox<number>
          id={`taxonomy-combobox-${uid}`}
          items={listboxItems}
          value={selectedId}
          onSelect={(id) => onSelect(id)}
          onCreate={onCreate}
          triggerLabel="—"
          selectedLabel={selected?.name}
          clearOption={
            selectedId !== null
              ? { label: 'Clear', onClear: () => onSelect(null) }
              : undefined
          }
        />
      </div>
    </div>
  );
}
