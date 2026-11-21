/**
 * Searchable single-select with a create-new option, for the correspondent and
 * document-type fields. Read-only mode shows the selected name as plain text.
 */
import React, { useId } from 'react';
import type { TaxonomyItem } from '../../../api/types';
import { FilterableListbox } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import type { FilterableItem } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import styles from './TaxonomyCombobox.module.css';

export interface TaxonomyComboboxProps {
  label: string;
  items: TaxonomyItem[];
  selectedId: number | null;
  canEdit: boolean;
  /** Called with `null` when the user picks "Clear". */
  onSelect: (id: number | null) => void;
  /** Called with the trimmed query when the user picks "Create <query>". */
  onCreate: (name: string) => void;
}

export function TaxonomyCombobox({
  label, items, selectedId, canEdit, onSelect, onCreate,
}: TaxonomyComboboxProps): React.ReactElement {
  const uid = useId();
  const selected = items.find((i) => i.id === selectedId) ?? null;

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
