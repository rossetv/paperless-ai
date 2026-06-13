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
 * Placeholder DocThumb body-row indices (0-based) highlighted when a source
 * card is in the default or highlighted state (FE-59). These drive the accent
 * lines inside the fallback SVG thumbnail — not matched content from the wire.
 */
const MATCHED_ROWS_HIGHLIGHTED = [3, 4, 7];
const MATCHED_ROWS_DEFAULT = [5, 6];

export interface SourceCardProps {
  /** The source document to display. */
  source: SourceDocument;
  /**
   * 1-based citation index corresponding to the [n] markers in the AnswerCard.
   * Shown as the badge so the user can cross-reference citations to sources.
   */
  index: number;
  /**
   * When true, visually highlights the card — used by the parent when the
   * user activates a CitationMark pointing to this source.
   */
  highlighted?: boolean;
  /**
   * Called with the document id when "View" is activated. The page opens
   * the in-app document-preview viewer for that id.
   */
  onPreview: (documentId: number) => void;
}

/**
 * Single search-result source card, restyled to the handoff design.
 *
 * Composes the `SourceCardSurface` shell (the two-column grid with the
 * thumbnail + citation badge) with: the `DocumentMeta` meta row, a
 * display-font title, the highlighted matched-content snippet, a "View"
 * button that opens the in-app viewer, and the relevance score.
 *
 * Note: `source.paperless_url` is present on the wire type but intentionally
 * not rendered — all document access goes through the in-app
 * DocumentPreviewScreen.
 *
 * Wrapped in `React.memo` — the `SourceList` parent can re-render (e.g. when
 * `highlightedIndex` changes for a different card) without touching every
 * sibling card whose props haven't changed.
 *
 * Composed from: SourceCardSurface, Text, Button, Stack, DocumentMeta,
 * SnippetText. No own CSS module (§12.5 — features layer is
 * composition-only).
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
        {/* Single-line meta row — correspondent · type · created */}
        <DocumentMeta source={source} />

        {/* Title — display-font emphasis */}
        {source.title !== null && source.title !== undefined && (
          <Text as="strong" variant="card-title">
            {source.title}
          </Text>
        )}

        {/* Highlighted matched-content snippet */}
        <SnippetText text={source.snippet} />

        {/* Actions row — preview + the relevance badge */}
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
 * Memoised export — re-renders only when source data, index, highlight state,
 * or the preview callback reference changes. The parent `SourceList` passes a
 * stable `onPreview` from the page level so memo holds across re-renders
 * triggered by `highlightedIndex` changing on other cards.
 */
export const SourceCard = React.memo(SourceCardInner);
