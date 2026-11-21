import React from 'react';
import { DocumentViewerChrome } from '../../../components/primitives/DocumentViewerChrome/DocumentViewerChrome';
import { ViewerSplit } from '../../../components/layout/ViewerSplit/ViewerSplit';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { Card } from '../../../components/primitives/Card/Card';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';
import { Text } from '../../../components/primitives/Text/Text';
import { RelevanceMeter } from '../../../components/primitives/RelevanceMeter/RelevanceMeter';
import { Stack } from '../../../components/layout/Stack/Stack';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { DocumentMeta } from '../../document/DocumentMeta/DocumentMeta';
import { documentPdfUrl } from '../../../api/client';
import type { PreviewableDocument } from '../../../api/types';

export interface DocumentPreviewScreenProps {
  /** A wire SourceDocument or a locally built one. */
  source: PreviewableDocument & { tags?: string[] };
  onClose: () => void;
  /**
   * Present when opened from a search result; absent for standalone opens
   * (library card, `/document/:id` link, index-failure preview).
   */
  searchContext?: {
    /** 1-based position in the results list. */
    sourceIndex: number;
    sourceCount: number;
  };
}

/**
 * The in-app document viewer: the PDF in an iframe of the proxy stream (the
 * browser's native viewer renders it) beside a metadata sidebar. The source
 * position and matched-content panel appear only with a `searchContext`.
 */
export function DocumentPreviewScreen({
  source,
  onClose,
  searchContext,
}: DocumentPreviewScreenProps): React.ReactElement {
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
            {/* Source position, only when opened from a search result */}
            {searchContext !== undefined && (
              <Stack direction="horizontal" gap={8} align="center">
                <CitationMark
                  index={searchContext.sourceIndex}
                />
                <Text as="span" variant="micro" tone="tertiary">
                  Source {searchContext.sourceIndex} of {searchContext.sourceCount}
                </Text>
              </Stack>
            )}

            {/* The title is already in the chrome breadcrumb. */}
            <DocumentMeta source={source} />

            {/* Matched content */}
            {searchContext !== undefined && source.snippet !== '' && (
              <Card>
                <Stack direction="vertical" gap={4}>
                  <Text as="span" variant="micro" tone="tertiary">
                    Matched in this document
                  </Text>
                  {source.relevance_tier !== undefined && (
                    <RelevanceMeter tier={source.relevance_tier} />
                  )}
                  <SnippetText text={source.snippet} />
                </Stack>
              </Card>
            )}

            {/* Tags */}
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
