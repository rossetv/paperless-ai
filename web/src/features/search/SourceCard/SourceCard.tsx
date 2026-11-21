import React from 'react';
import { SourceCardSurface } from '../../../components/primitives/SourceCardSurface/SourceCardSurface';
import { Text } from '../../../components/primitives/Text/Text';
import { Button } from '../../../components/primitives/Button/Button';
import { Stack } from '../../../components/layout/Stack/Stack';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';
import { RelevanceMeter } from '../../../components/primitives/RelevanceMeter/RelevanceMeter';
import { documentThumbUrl } from '../../../api/client';
import type { SourceDocument } from '../../../api/types';
import { thumbKindForDocumentType } from '../../../components/primitives/DocThumb/thumbKind';

/**
 * Accent rows (0-based) in the fallback SVG thumbnail. Decorative only, not
 * matched content from the wire.
 */
const MATCHED_ROWS_HIGHLIGHTED = [3, 4, 7];
const MATCHED_ROWS_DEFAULT = [5, 6];

export interface SourceCardProps {
  source: SourceDocument;
  /** 1-based citation index, matching the [n] markers in the AnswerCard. */
  index: number;
  /** Set when the user activates a CitationMark pointing at this source. */
  highlighted?: boolean;
  onPreview: (documentId: number) => void;
}

/**
 * One search-result source card. `source.paperless_url` is deliberately not
 * rendered: all document access goes through the in-app DocumentPreviewScreen.
 */
function SourceCardInner({
  source,
  index,
  highlighted = false,
  onPreview,
}: SourceCardProps): React.ReactElement {
  return (
    <SourceCardSurface
      index={index}
      thumbKind={thumbKindForDocumentType(source.document_type)}
      thumbImageUrl={documentThumbUrl(source.document_id)}
      matched={highlighted ? MATCHED_ROWS_HIGHLIGHTED : MATCHED_ROWS_DEFAULT}
      highlighted={highlighted}
    >
      <Stack direction="vertical" gap={5}>
        {/* Meta row */}
        <DocumentMeta source={source} />

        {/* Title */}
        {source.title !== null && source.title !== undefined && (
          <Text as="strong" variant="card-title">
            {source.title}
          </Text>
        )}

        {/* Matched-content snippet */}
        <SnippetText text={source.snippet} />

        {/* Actions */}
        <Stack direction="horizontal" gap={6} align="center" wrap>
          <Button
            variant="primary"
            size="small"
            onClick={() => onPreview(source.document_id)}
          >
            View
          </Button>
          <RelevanceMeter tier={source.relevance_tier} />
        </Stack>
      </Stack>
    </SourceCardSurface>
  );
}

/**
 * Memoised so a `highlightedIndex` change in `SourceList` only re-renders the
 * affected cards; relies on the page passing a stable `onPreview`.
 */
export const SourceCard = React.memo(SourceCardInner);
