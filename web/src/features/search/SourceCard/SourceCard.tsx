import React from 'react';
import { Card } from '../../../components/primitives/Card/Card';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Link } from '../../../components/primitives/Link/Link';
import { Stack } from '../../../components/layout/Stack/Stack';
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
 * Displays: citation index badge, document title, correspondent, document
 * type, creation date, snippet, and an "Open in Paperless" external link.
 *
 * All optional fields from SourceDocument (title, correspondent, etc.) are
 * handled gracefully — null fields are omitted from the rendered output.
 *
 * The "Open in Paperless" link uses the Link primitive with external=true,
 * which sets target="_blank" and rel="noopener noreferrer" automatically.
 *
 * Composed from: Card, Badge, Link, Stack.
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
            <strong>{source.title}</strong>
          )}
        </Stack>

        {/* Metadata row: correspondent, document type, date */}
        <Stack direction="horizontal" gap={4} wrap>
          {source.correspondent !== null && source.correspondent !== undefined && (
            <Badge variant="neutral">{source.correspondent}</Badge>
          )}
          {source.document_type !== null && source.document_type !== undefined && (
            <Badge variant="neutral">{source.document_type}</Badge>
          )}
          {source.created !== null && source.created !== undefined && (
            <time dateTime={source.created}>{source.created}</time>
          )}
        </Stack>

        {/* Snippet */}
        <p>{source.snippet}</p>

        {/* External link to Paperless document */}
        <Link href={source.paperless_url} external variant="default">
          Open in Paperless
        </Link>
      </Stack>
    </Card>
  );
}
