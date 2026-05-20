import React from 'react';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Stack } from '../../../components/layout/Stack/Stack';
import type { SourceDocument } from '../../../api/types';

export interface DocumentMetaProps {
  /**
   * The source document whose metadata is to be displayed.
   * All fields except document_id, snippet, paperless_url, and score may be
   * null — the component renders gracefully when any of them are absent.
   */
  source: SourceDocument;
}

/**
 * Compact metadata row for a document.
 *
 * Renders correspondent, document type, and created date as inline badges/chips.
 * Missing (null) fields are silently omitted — a document with no correspondent
 * or type renders correctly with only the non-null fields shown.
 *
 * Uses a <time> element with a dateTime attribute for the created date so that
 * assistive technology and machine readers can parse the ISO date.
 *
 * Composed from: Badge, Stack.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function DocumentMeta({ source }: DocumentMetaProps): React.ReactElement {
  return (
    <Stack direction="horizontal" gap={4} wrap>
      {source.correspondent !== null && source.correspondent !== undefined && (
        <Badge variant="neutral">{source.correspondent}</Badge>
      )}
      {source.document_type !== null && source.document_type !== undefined && (
        <Badge variant="neutral">{source.document_type}</Badge>
      )}
      {source.created !== null && source.created !== undefined && (
        <time dateTime={source.created}>
          <Badge variant="neutral">{source.created}</Badge>
        </time>
      )}
    </Stack>
  );
}
