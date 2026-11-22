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
  const wrapRef = React.useRef<HTMLDivElement>(null);
  // Index of the chip just removed; focus is placed once the chip is gone.
  const removedIndex = React.useRef<number | null>(null);

  React.useEffect(() => {
    const index = removedIndex.current;
    if (index === null) return;
    removedIndex.current = null;
    // Focus that moved on its own, e.g. into an open Add tag list, stays there.
    if (document.activeElement !== null && document.activeElement !== document.body) return;
    // Buttons are the remove buttons in chip order, then the Add tag trigger.
    const buttons = wrapRef.current?.querySelectorAll('button');
    if (buttons === undefined || buttons.length === 0) return;
    const chipCount = buttons.length - 1;
    buttons[chipCount === 0 ? 0 : Math.min(index, chipCount - 1)]?.focus();
  }, [selectedIds]);

  const selectedRows = selectedIds.map((id) => {
    const found = availableTags.find((t) => t.id === id);
    return { id, name: found?.name ?? `#${id}` };
  });

  const selectableItems: FilterableItem<number>[] = availableTags
    .filter((t) => !selectedIds.includes(t.id))
    .map((t) => ({
      value: t.id,
      label: t.name,
      meta: `${t.document_count} ${t.document_count === 1 ? 'doc' : 'docs'}`,
    }));

  // Suppresses "Create …" when the query matches an already-selected tag, which
  // is missing from selectableItems.
  const allTagNames: string[] = availableTags.map((t) => t.name);

  return (
    <div ref={wrapRef} className={styles['wrap']}>
      {selectedRows.map((t, index) =>
        canEdit ? (
          <Chip
            key={t.id}
            onRemove={() => {
              removedIndex.current = index;
              onRemove(t.id);
            }}
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
