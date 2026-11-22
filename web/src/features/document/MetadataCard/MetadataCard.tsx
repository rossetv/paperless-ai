/**
 * Document details sidebar card: correspondent, document type and date.
 *
 * ASN and Notes are absent because `LibraryDocument` does not carry them.
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
  document: LibraryDocument;
  correspondents: TaxonomyItem[];
  documentTypes: TaxonomyItem[];
  canEdit: boolean;
  /** Each call carries only the fields that changed. */
  onPatch: (patch: MetadataPatch) => void;
  onCreateCorrespondent: (name: string) => void;
  onCreateDocumentType: (name: string) => void;
}

/**
 * Resolve a taxonomy id by name; null means nothing selected. Known limitation:
 * a rename in Paperless breaks the lookup until the next index reconcile.
 */
function resolveId(items: TaxonomyItem[], name: string | null): number | null {
  if (name === null) return null;
  return items.find((i) => i.name === name)?.id ?? null;
}


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
  // The API sends a full offset timestamp; the date input and the PATCH need the
  // bare `YYYY-MM-DD`. An empty string shows the "No date" placeholder.
  const dateValue = isoDateOnly(document.created);
  const dateDisplay = document.created === null ? '' : formatLongDate(document.created);

  return (
    <Card>
      <h2 className={styles['card-h']}>Details</h2>

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
