import React from 'react';
import { SourceCardSurface } from '../../../components/primitives/SourceCardSurface/SourceCardSurface';
import type { DocThumbKind } from '../../../components/primitives/DocThumb/DocThumb';
import { Text } from '../../../components/primitives/Text/Text';
import { Button } from '../../../components/primitives/Button/Button';
import { Link } from '../../../components/primitives/Link/Link';
import { Stack } from '../../../components/layout/Stack/Stack';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { DocumentSnippet } from '../../document/DocumentSnippet/DocumentSnippet';
import type { SourceDocument } from '../../../api/types';

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
   * user activates a CitationLink pointing to this source.
   */
  highlighted?: boolean;
  /**
   * Called with the document id when "Preview" is activated. The page opens
   * the in-app document-preview viewer for that id.
   */
  onPreview: (documentId: number) => void;
}

/**
 * Pick a thumbnail style from the document's type.
 *
 * The `DocThumb` primitive offers three page shapes; map the free-text
 * Paperless document type onto the nearest one, defaulting to a statement.
 */
function thumbKindFor(documentType: string | null): DocThumbKind {
  const type = (documentType ?? '').toLowerCase();
  if (type.includes('invoice') || type.includes('receipt')) {
    return 'invoice';
  }
  if (type.includes('letter') || type.includes('notification')) {
    return 'letter';
  }
  return 'statement';
}

/**
 * Single search-result source card, restyled to the handoff design.
 *
 * Composes the `SourceCardSurface` shell (the two-column grid with the
 * thumbnail + citation badge) with: the `DocumentMeta` meta row, a
 * display-font title, the highlighted `DocumentSnippet`, a "Preview" button
 * that opens the in-app viewer, an "Open in Paperless" external link, and the
 * relevance score. The metadata and snippet are the shared `document`
 * features — not re-implemented here.
 *
 * Composed from: SourceCardSurface, Text, Button, Link, Stack, DocumentMeta,
 * DocumentSnippet. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function SourceCard({
  source,
  index,
  highlighted = false,
  onPreview,
}: SourceCardProps): React.ReactElement {
  return (
    <SourceCardSurface
      index={index}
      thumbKind={thumbKindFor(source.document_type)}
      matched={highlighted ? [3, 4, 7] : [5, 6]}
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
        <DocumentSnippet snippet={source.snippet} />

        {/* Actions row — preview, open externally, relevance */}
        <Stack direction="horizontal" gap={6} align="center" wrap>
          <Button
            variant="primary"
            size="small"
            onClick={() => onPreview(source.document_id)}
          >
            Preview
          </Button>
          {source.paperless_url != null && source.paperless_url !== '' && (
            <Link href={source.paperless_url} external variant="default">
              Open in Paperless
            </Link>
          )}
          <Text as="span" variant="micro" tone="tertiary">
            relevance · {source.score.toFixed(2)}
          </Text>
        </Stack>
      </Stack>
    </SourceCardSurface>
  );
}
