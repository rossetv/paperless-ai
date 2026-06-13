import React from 'react';
import { documentPdfUrl } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Link } from '../../../components/primitives/Link/Link';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
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
 *   - Download — proxied PDF download via the API. This is the in-app action,
 *     so it keeps the primary action emphasis.
 *   - Open in Paperless — external Link to the source Paperless instance,
 *     deliberately demoted to a secondary/inline link so leaving the app reads
 *     as lower-priority than the in-app action (UI-24, DD-3). Omitted when null.
 *
 * The PDF iframe sits over an app-owned dark backdrop: the viewport and a
 * placeholder layer both fill with --colour-surface-dark and the placeholder
 * carries a "Couldn't load preview" warning EmptyState. The backdrop paints
 * before (and behind) the iframe, so an unloaded or failed iframe never flashes
 * bright white — the viewer area is dark from first paint (UI-03).
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
      <div className={styles['toolbar']}>
        <a
          className={styles['action']}
          href={pdfUrl}
          download
        >
          <Icon name="document" size="small" />
          Download
        </a>
        {paperlessUrl !== null && (
          <Link
            href={paperlessUrl}
            external
            className={cn(styles['external-action'])}
          >
            <Icon name="external-link" size="small" />
            Open in Paperless
          </Link>
        )}
      </div>
      <div className={styles['viewport']}>
        <div className={styles['placeholder']} aria-hidden="true">
          <EmptyState icon="warning" message="Couldn't load preview" />
        </div>
        <PdfFrame
          src={pdfUrl}
          title={`${title} PDF`}
          className={cn(styles['frame'])}
        />
      </div>
    </Card>
  );
}
