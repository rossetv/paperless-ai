import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Link } from '../../../components/primitives/Link/Link';
import { Text } from '../../../components/primitives/Text/Text';
import { Stack } from '../../../components/layout/Stack/Stack';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { DocumentSnippet } from '../../document/DocumentSnippet/DocumentSnippet';
import type { SourceDocument } from '../../../api/types';

export interface SourceCardProps {
  /** The source document to display. */
  source: SourceDocument;
  /**
   * 1-based citation index corresponding to the [n] markers in the AnswerCard.
   * Displayed as a badge so the user can cross-reference citations to sources.
   */
  index: number;
  /**
   * When true, visually highlights the card — used by the parent when the
   * user activates a CitationLink pointing to this source.
   */
  highlighted?: boolean;
}

/**
 * Single search result card.
 *
 * Displays: citation index badge, document title, the document metadata row,
 * the matched-content snippet, and an "Open in Paperless" external link.
 *
 * The metadata row and the snippet are NOT re-implemented here — they are the
 * `DocumentMeta` and `DocumentSnippet` document features, composed directly,
 * so a search result and a bare document render their metadata identically.
 * The title routes through the `Text` typography primitive.
 *
 * The "Open in Paperless" link uses the Link primitive with external=true,
 * which sets target="_blank" and rel="noopener noreferrer" automatically.
 *
 * Composed from: Card, Badge, Link, Text, Stack, DocumentMeta, DocumentSnippet.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function SourceCard({
  source,
  index,
  highlighted = false,
}: SourceCardProps): React.ReactElement {
  return (
    <Card as="article" elevated={highlighted}>
      <Stack direction="vertical" gap={5}>
        {/* Header row: citation badge + title */}
        <Stack direction="horizontal" gap={4} align="center">
          <Badge variant="accent">[{index}]</Badge>
          {source.title !== null && source.title !== undefined && (
            <Text as="strong" variant="body-emphasis">
              {source.title}
            </Text>
          )}
        </Stack>

        {/* Metadata row — the DocumentMeta feature, not an inline copy */}
        <DocumentMeta source={source} />

        {/* Snippet — the DocumentSnippet feature, not an inline copy */}
        <DocumentSnippet snippet={source.snippet} />

        {/* External link to Paperless document */}
        <Link href={source.paperless_url} external variant="default">
          Open in Paperless
        </Link>
      </Stack>
    </Card>
  );
}
