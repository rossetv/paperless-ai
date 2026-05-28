import React from 'react';
import { documentPdfUrl } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { cn } from '../../../lib/cn';
import styles from './PdfViewerCard.module.css';

export interface PdfViewerCardProps {
  /** Paperless-ngx document ID — used to build the proxy PDF URL. */
  documentId: number;
  /** Document title — surfaced as the iframe's accessible title. */
  title: string;
  /**
   * Full Paperless-ngx URL for the document detail page.
   * When null the "Open in Paperless" action is omitted.
   */
  paperlessUrl: string | null;
}

/**
 * Self-contained card that embeds the PDF viewer for a single document.
 *
 * Toolbar contains only:
 *   - Download — proxied PDF download via the API.
 *   - Open in Paperless — external link to the source Paperless instance (omitted when null).
 *
 * Pager and zoom are intentionally absent; the browser's native PDF chrome handles them.
 *
 * Tier: features/document (CODE_GUIDELINES §12.3). Imports from components/* and api/.
 */
export function PdfViewerCard({
  documentId,
  title,
  paperlessUrl,
}: PdfViewerCardProps): React.ReactElement {
  const pdfUrl = documentPdfUrl(documentId);

  return (
    <Card as="section" className={cn(styles['card'])}>
      <div className={cn(styles['toolbar'])}>
        <a
          className={cn(styles['action'])}
          href={pdfUrl}
          download
        >
          <Icon name="document" size="small" />
          Download
        </a>
        {paperlessUrl !== null && (
          <a
            className={cn(styles['action'], styles['action-primary'])}
            href={paperlessUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Icon name="external-link" size="small" />
            Open in Paperless
          </a>
        )}
      </div>
      <PdfFrame
        src={pdfUrl}
        title={`${title} PDF`}
        className={cn(styles['frame'])}
      />
    </Card>
  );
}
