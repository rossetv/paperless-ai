/**
 * TagEditor — multi-select tag chips with inline add / remove / create.
 *
 * Renders one chip per selected tag id. When `canEdit` is true:
 *  - Each chip carries a × dismiss button (via the Chip primitive's onRemove).
 *  - A FilterableListbox in multi-select mode lists only the tags not already
 *    selected. Typing filters options; an unmatched query reveals a "Create
 *    <query>" row that calls onCreate. Full keyboard navigation and ARIA
 *    combobox semantics are provided by the primitive (FE-04/05/23).
 *
 * Stale ids (present in selectedIds but absent from availableTags) render as
 * "#<id>" chips and remain removable.
 */
import React, { useId } from 'react';
import { Chip } from '../../../components/primitives/Chip/Chip';
import type { TaxonomyItem } from '../../../api/types';
import { FilterableListbox } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import type { FilterableItem } from '../../../components/patterns/FilterableListbox/FilterableListbox';
import styles from './TagEditor.module.css';

export interface TagEditorProps {
  /** IDs of the currently-selected tags. */
  selectedIds: number[];
  /** Full list of available tags from the taxonomy endpoint. */
  availableTags: TaxonomyItem[];
  /** When false, all editing controls are hidden. */
  canEdit: boolean;
  /** Called with the tag id when the user selects an existing tag. */
  onAdd: (id: number) => void;
  /** Called with the tag id when the user removes a tag chip. */
  onRemove: (id: number) => void;
  /** Called with the trimmed name when the user creates a new tag. */
  onCreate: (name: string) => void;
}

/**
 * Inline multi-tag editor.
 *
 * When canEdit=true, renders removable chips plus a "+ Add tag" trigger that
 * opens a filtered combobox. When canEdit=false, renders read-only chips only.
 */
export function TagEditor({
  selectedIds,
  availableTags,
  canEdit,
  onAdd,
  onRemove,
  onCreate,
}: TagEditorProps): React.ReactElement {
  const uid = useId();

  // Resolve each selected id to its name; fall back to "#<id>" for stale ids.
  const selectedRows = selectedIds.map((id) => {
    const found = availableTags.find((t) => t.id === id);
    return { id, name: found?.name ?? `#${id}` };
  });

  // Offer only tags not already selected so the listbox never shows duplicates.
  const selectableItems: FilterableItem<number>[] = availableTags
    .filter((t) => !selectedIds.includes(t.id))
    .map((t) => ({
      value: t.id,
      label: t.name,
      meta: `${t.document_count} docs`,
    }));

  // Full set of existing tag names — used by FilterableListbox to suppress the
  // "Create …" row when the typed query matches an ALREADY-SELECTED tag
  // (which is absent from selectableItems but must not be duplicated).
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
