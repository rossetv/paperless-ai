import React from 'react';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Stack } from '../../../components/layout/Stack/Stack';
import type { PreviewableDocument } from '../../../api/types';
import { formatShortDate } from '../../../lib/formatDate';

export interface DocumentMetaProps {
  source: PreviewableDocument;
}

/**
 * Compact row of correspondent, document type and created date badges. Null
 * fields are omitted.
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
          <Badge variant="neutral">{formatShortDate(source.created)}</Badge>
        </time>
      )}
    </Stack>
  );
}
