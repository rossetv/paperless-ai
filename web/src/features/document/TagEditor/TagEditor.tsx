/**
 * Tag chips with inline add, remove and create. Stale ids (selected but not in
 * `availableTags`) render as removable "#<id>" chips.
 */
import React, { useId } from 'react';
import { Chip } from '../../../components/primitives/Chip/Chip';
import type { TaxonomyItem } from '../../../api/types';
import { FilterableListbox } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import type { FilterableItem } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import styles from './TagEditor.module.css';

export interface TagEditorProps {
  selectedIds: number[];
  availableTags: TaxonomyItem[];
  /** When false, all editing controls are hidden. */
  canEdit: boolean;
  onAdd: (id: number) => void;
  onRemove: (id: number) => void;
  /** Called with the trimmed name. */
  onCreate: (name: string) => void;
}

export function TagEditor({
  selectedIds,
  availableTags,
  canEdit,
  onAdd,
  onRemove,
  onCreate,
}: TagEditorProps): React.ReactElement {
  const uid = useId();

  const selectedRows = selectedIds.map((id) => {
    const found = availableTags.find((t) => t.id === id);
    return { id, name: found?.name ?? `#${id}` };
  });

  const selectableItems: FilterableItem<number>[] = availableTags
    .filter((t) => !selectedIds.includes(t.id))
    .map((t) => ({
      value: t.id,
      label: t.name,
      meta: `${t.document_count} docs`,
    }));

  // Suppresses "Create …" when the query matches an already-selected tag, which
  // is missing from selectableItems.
  const allTagNames: string[] = availableTags.map((t) => t.name);

  return (
    <div className={styles['wrap']}>
      {selectedRows.map((t) =>
        canEdit ? (
          <Chip
            key={t.id}
            onRemove={() => onRemove(t.id)}
            removeLabel={`Remove ${t.name}`}
          >
            {t.name}
          </Chip>
        ) : (
          <Chip key={t.id}>{t.name}</Chip>
        ),
      )}

      {canEdit && (
        <FilterableListbox<number>
          id={`tag-editor-${uid}`}
          items={selectableItems}
          value={selectedIds}
          onSelect={(id) => onAdd(id)}
          onCreate={onCreate}
          multiple
          triggerLabel="+ Add tag"
          existingNames={allTagNames}
        />
      )}
    </div>
  );
}
