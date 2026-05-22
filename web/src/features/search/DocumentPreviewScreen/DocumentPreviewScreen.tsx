import React from 'react';
import { DocumentViewerChrome } from '../../../components/primitives/DocumentViewerChrome/DocumentViewerChrome';
import { ViewerSplit } from '../../../components/layout/ViewerSplit/ViewerSplit';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { Card } from '../../../components/primitives/Card/Card';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';
import { Text } from '../../../components/primitives/Text/Text';
import { Stack } from '../../../components/layout/Stack/Stack';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { documentPdfUrl } from '../../../api/client';
import type { SourceDocument } from '../../../api/types';

export interface DocumentPreviewScreenProps {
  /** The source document to preview. */
  source: SourceDocument;
  /** Called when the viewer is closed — the page returns to the results. */
  onClose: () => void;
}

/**
 * The in-app document-preview viewer.
 *
 * The forced-dark `DocumentViewerChrome` shell wraps a `ViewerSplit`: the
 * left side embeds the PDF via `PdfFrame` (an `<iframe>` of the
 * `/api/documents/{id}/pdf` proxy stream — the browser's native viewer does
 * the rendering); the right side is a metadata sidebar with the document's
 * `DocumentMeta`, its relevance, and the matched-content snippet.
 *
 * The wire `SourceDocument` carries one `snippet`, so the sidebar shows that
 * single matched excerpt — the handoff's multi-chunk list is not backed by
 * the contract.
 *
 * Composed from: DocumentViewerChrome, ViewerSplit, PdfFrame, Card, Text,
 * SnippetText, Stack, DocumentMeta. No own CSS module (§12.5 — features
 * layer is composition-only).
 */
export function DocumentPreviewScreen({
  source,
  onClose,
}: DocumentPreviewScreenProps): React.ReactElement {
  // The title may be null; fall back to a stable id-based label.
  const title = source.title ?? `Document ${source.document_id}`;
  const pdfUrl = documentPdfUrl(source.document_id);

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
          </Stack>
        }
      >
        <PdfFrame src={pdfUrl} title={`${title} PDF`} />
      </ViewerSplit>
    </DocumentViewerChrome>
  );
}
