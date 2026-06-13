/**
 * MetadataCard — document details sidebar card.
 *
 * Renders three editable rows: Correspondent, Document type, and Document date.
 * Uses TaxonomyCombobox for the taxonomy pickers and EditableField for the date.
 *
 * ASN (archive serial number) and Notes are intentionally omitted from v1 because
 * `LibraryDocument` does not carry those fields (the GET response doesn't return
 * them). They can be added in a follow-up once the wire shape is extended.
 */
import React from 'react';
import type { LibraryDocument, TaxonomyItem } from '../../../api/types';
import { Card } from '../../../components/primitives/Card/Card';
import { TaxonomyCombobox } from '../TaxonomyCombobox/TaxonomyCombobox';
import { EditableField } from '../EditableField/EditableField';
import { formatLongDate, isoDateOnly } from '../../../lib/formatDate';
import styles from './MetadataCard.module.css';

/** Subset of a PATCH request covered by MetadataCard. */
export interface MetadataPatch {
  correspondent_id?: number | null;
  document_type_id?: number | null;
  document_date?: string | null;
}

export interface MetadataCardProps {
  /** The document being displayed/edited. */
  document: LibraryDocument;
  /** Full correspondent list from the taxonomy endpoint. */
  correspondents: TaxonomyItem[];
  /** Full document-type list from the taxonomy endpoint. */
  documentTypes: TaxonomyItem[];
  /** Whether the current user may edit the fields. */
  canEdit: boolean;
  /**
   * Called with the changed field(s) when the user commits an edit.
   * Each call carries only the fields that changed.
   */
  onPatch: (patch: MetadataPatch) => void;
  /** Called with the name when the user creates a new correspondent inline. */
  onCreateCorrespondent: (name: string) => void;
  /** Called with the name when the user creates a new document type inline. */
  onCreateDocumentType: (name: string) => void;
}

/**
 * Resolve a taxonomy item id from a name string.
 *
 * Returns null when the name is null or not found — the caller treats null as
 * "nothing selected". This name-based lookup is a known v1 limitation: a rename
 * in Paperless would break resolution until the next index reconcile.
 */
function resolveId(items: TaxonomyItem[], name: string | null): number | null {
  if (name === null) return null;
  return items.find((i) => i.name === name)?.id ?? null;
}


/**
 * Sidebar card showing correspondent, document type, and document date.
 *
 * In read-only mode (`canEdit=false`) all fields render as plain text.
 * In editable mode the taxonomy fields open a TaxonomyCombobox and the date
 * field uses EditableField with `type="date"`.
 */
export function MetadataCard({
  document,
  correspondents,
  documentTypes,
  canEdit,
  onPatch,
  onCreateCorrespondent,
  onCreateDocumentType,
}: MetadataCardProps): React.ReactElement {
  const correspondentId = resolveId(correspondents, document.correspondent);
  const documentTypeId = resolveId(documentTypes, document.document_type);
  // The API returns the document date as a full offset timestamp
  // (`2026-01-13T00:00:00+00:00`). The editable input and the PATCH need the
  // bare `YYYY-MM-DD`; the view text shows the formatted long date. An empty
  // string drives the "No date" placeholder in both modes.
  const dateValue = isoDateOnly(document.created);
  const dateDisplay = document.created === null ? '' : formatLongDate(document.created);

  return (
    <Card>
      <h3 className={styles['card-h']}>Details</h3>

      <TaxonomyCombobox
        label="Correspondent"
        items={correspondents}
        selectedId={correspondentId}
        canEdit={canEdit}
        onSelect={(id) => onPatch({ correspondent_id: id })}
        onCreate={onCreateCorrespondent}
      />

      <TaxonomyCombobox
        label="Document type"
        items={documentTypes}
        selectedId={documentTypeId}
        canEdit={canEdit}
        onSelect={(id) => onPatch({ document_type_id: id })}
        onCreate={onCreateDocumentType}
      />

      {canEdit ? (
        <EditableField
          label="Date"
          value={dateValue}
          displayValue={dateDisplay}
          canEdit={true}
          type="date"
          placeholder="No date"
          onCommit={(next) => onPatch({ document_date: next === '' ? null : next })}
        />
      ) : (
        <EditableField
          label="Date"
          value={dateValue}
          displayValue={dateDisplay}
          canEdit={false}
          placeholder="No date"
          onCommit={() => undefined}
        />
      )}
    </Card>
  );
}
