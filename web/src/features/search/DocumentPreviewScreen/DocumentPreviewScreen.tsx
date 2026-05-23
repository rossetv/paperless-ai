import React from 'react';
import { DocumentViewerChrome } from '../../../components/primitives/DocumentViewerChrome/DocumentViewerChrome';
import { ViewerSplit } from '../../../components/layout/ViewerSplit/ViewerSplit';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { Card } from '../../../components/primitives/Card/Card';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';
import { Text } from '../../../components/primitives/Text/Text';
import { Stack } from '../../../components/layout/Stack/Stack';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { documentPdfUrl } from '../../../api/client';
import type { PreviewableDocument } from '../../../api/types';

export interface DocumentPreviewScreenProps {
  /** The document to preview. Accepts wire SourceDocuments and locally-fabricated objects. */
  source: PreviewableDocument & { tags?: string[] };
  /** Called when the viewer is closed — the page returns to the results. */
  onClose: () => void;
  /** 1-based position of this source in the results list. */
  sourceIndex: number;
  /** Total number of sources in the results list. */
  sourceCount: number;
}

/**
 * The in-app document-preview viewer.
 *
 * The forced-dark `DocumentViewerChrome` shell wraps a `ViewerSplit`: the
 * left side embeds the PDF via `PdfFrame` (an `<iframe>` of the
 * `/api/documents/{id}/pdf` proxy stream — the browser's native viewer does
 * the rendering); the right side is a metadata sidebar with the document's
 * `DocumentMeta`, its relevance, the matched-content snippet, and any tags.
 *
 * The sidebar header shows a `CitationMark` badge ([N]) and a "Source N of M"
 * caption so the user knows which result they are viewing.
 *
 * The wire `SourceDocument` carries one `snippet`, so the sidebar shows that
 * single matched excerpt. Rendering multiple chunk cards (as in the design
 * handoff) requires the API to expose multiple chunks per source — future
 * enhancement once the backend contract is extended.
 *
 * Composed from: DocumentViewerChrome, ViewerSplit, PdfFrame, Card, Text,
 * SnippetText, Stack, CitationMark, Chip, DocumentMeta. No own CSS module
 * (§12.5 — features layer is composition-only).
 */
export function DocumentPreviewScreen({
  source,
  onClose,
  sourceIndex,
  sourceCount,
}: DocumentPreviewScreenProps): React.ReactElement {
  // The title may be null; fall back to a stable id-based label.
  const title = source.title ?? `Document ${source.document_id}`;
  const pdfUrl = documentPdfUrl(source.document_id);
  const tags = source.tags ?? [];

  return (
    <DocumentViewerChrome
      title={title}
      paperlessUrl={source.paperless_url}
      downloadUrl={pdfUrl}
      onClose={onClose}
    >
      <ViewerSplit
        sidebar={
          <Stack direction="vertical" gap={10}>
            {/* Source position header — citation badge + "Source N of M" caption. */}
            <Stack direction="horizontal" gap={8} align="center">
              <CitationMark index={sourceIndex} onActivate={() => {}} />
              <Text as="span" variant="micro" tone="tertiary">
                Source {sourceIndex} of {sourceCount}
              </Text>
            </Stack>

            {/* Document identity — the title is already shown in the chrome breadcrumb; show only the meta row here. */}
            <DocumentMeta source={source} />

            {/* Matched-content panel. */}
            <Card>
              <Stack direction="vertical" gap={4}>
                <Text as="span" variant="micro" tone="tertiary">
                  Matched in this document · relevance{' '}
                  {source.score.toFixed(2)}
                </Text>
                <SnippetText text={source.snippet} />
              </Stack>
            </Card>

            {/* Tags — only rendered when the source carries at least one tag. */}
            {tags.length > 0 && (
              <Stack direction="vertical" gap={6}>
                <Text as="span" variant="micro" tone="tertiary">
                  TAGS
                </Text>
                <Stack direction="horizontal" gap={6} wrap>
                  {tags.map((tag) => (
                    <Chip key={tag}>{tag}</Chip>
                  ))}
                </Stack>
              </Stack>
            )}
          </Stack>
        }
      >
        <PdfFrame src={pdfUrl} title={`${title} PDF`} />
      </ViewerSplit>
    </DocumentViewerChrome>
  );
}
