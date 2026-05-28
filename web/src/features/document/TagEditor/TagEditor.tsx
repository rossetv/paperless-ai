/**
 * TagEditor — multi-select tag chips with inline add / remove / create.
 *
 * Renders one chip per selected tag id. When `canEdit` is true:
 *  - Each chip carries a × dismiss button (via the Chip primitive's onRemove).
 *  - A "+ Add tag" chip-shaped button opens a combobox that lists only the
 *    tags not already selected. Typing filters options; an unmatched query
 *    reveals a "Create <query>" row that calls onCreate. Selecting an option
 *    or creating a new tag closes the combobox.
 *
 * Stale ids (present in selectedIds but absent from availableTags) render as
 * "#<id>" chips and remain removable.
 *
 * The onMouseDown + preventDefault pattern on listbox options is intentional:
 * without it the input's onBlur fires first, closing the combobox before the
 * click is registered.
 */
import React from 'react';
import { Chip } from '../../../components/primitives/Chip/Chip';
import type { TaxonomyItem } from '../../../api/types';
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
  const [adding, setAdding] = React.useState(false);
  const [query, setQuery] = React.useState('');

  // Resolve each selected id to its name; fall back to "#<id>" for stale ids.
  const selectedRows = selectedIds.map((id) => {
    const found = availableTags.find((t) => t.id === id);
    return { id, name: found?.name ?? `#${id}` };
  });

  // Tags the user can still add (those not already selected).
  const selectable = availableTags.filter((t) => !selectedIds.includes(t.id));
  const q = query.trim().toLowerCase();
  const filtered = selectable.filter((t) => t.name.toLowerCase().includes(q));

  // Create-new row: only when query is non-empty AND no tag (selected or not)
  // has the same name case-insensitively. This prevents duplicating an existing
  // tag even if it is already selected.
  const exact = availableTags.some((t) => t.name.toLowerCase() === q);
  const showCreate = q !== '' && !exact;

  function close(): void {
    setAdding(false);
    setQuery('');
  }

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

      {canEdit && !adding && (
        <button
          type="button"
          className={styles['add-btn']}
          aria-label="Add tag"
          onClick={() => setAdding(true)}
        >
          + Add tag
        </button>
      )}

      {canEdit && adding && (
        <div className={styles['combo']}>
          <input
            role="combobox"
            aria-expanded
            autoFocus
            className={styles['input']}
            value={query}
            placeholder="Type to search…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') close(); }}
            onBlur={close}
          />
          <ul role="listbox" className={styles['list']}>
            {filtered.map((t) => (
              <li
                key={t.id}
                role="option"
                className={styles['opt']}
                // onMouseDown + preventDefault prevents the input's onBlur from firing
                // before the click is registered in real browsers. onClick fires the
                // handler (and also catches fireEvent.click in tests).
                onMouseDown={(e) => { e.preventDefault(); }}
                onClick={() => { onAdd(t.id); close(); }}
              >
                {t.name}
                <small>{t.document_count} docs</small>
              </li>
            ))}
            {showCreate && (
              <li
                role="option"
                className={styles['create']}
                onMouseDown={(e) => { e.preventDefault(); }}
                onClick={() => { onCreate(query.trim()); close(); }}
              >
                Create "{query.trim()}"
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
