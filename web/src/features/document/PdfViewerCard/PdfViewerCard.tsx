import React from 'react';
import { documentPdfUrl } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { DocumentActions } from '../DocumentActions/DocumentActions';
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
  /**
   * Suggested filename for the Download anchor (e.g. "Allianz Invoice 2026.pdf").
   * Sets the `download` attribute so the browser uses this name rather than
   * deriving one from the proxy URL path (which ends in "/pdf", producing "pdf.pdf").
   */
  downloadFilename: string;
}

/**
 * Self-contained card that embeds the PDF viewer for a single document.
 *
 * The document-level actions (Download, Open in Paperless) live in the page's
 * `DocumentActions` row under the title — not on this card — so the viewer is
 * just the framed page. When the frame fails to load, the same `DocumentActions`
 * are offered inside the error state as escape hatches (Download is the in-app
 * action, Open in Paperless the demoted external link — UI-24 / DD-3).
 *
 * The PDF iframe sits over an app-owned dark backdrop: the viewport fills with
 * --colour-surface-dark so an unloaded iframe never flashes bright white. When
 * the frame reports a load failure (a 4xx/5xx proxy response, a refused-framing
 * response, or a stalled stream — all of which would otherwise show the
 * browser's grey error box), an app-owned dark error EmptyState is rendered
 * *over* the frame, with the same Download / Open-in-Paperless escape hatches.
 * The user never sees the bare grey iframe box (UI-03).
 *
 * Pager and zoom are intentionally absent; the browser's native PDF chrome handles them.
 *
 * Tier: features/document (CODE_GUIDELINES §12.3). Imports from components/* and api/.
 */
export function PdfViewerCard({
  documentId,
  title,
  paperlessUrl,
  downloadFilename,
}: PdfViewerCardProps): React.ReactElement {
  const pdfUrl = documentPdfUrl(documentId);
  const [failed, setFailed] = React.useState(false);

  // A new document gets a fresh chance to load before any stale failure shows.
  React.useEffect(() => {
    setFailed(false);
  }, [documentId]);

  return (
    <Card as="section" className={cn(styles['card'])}>
      <div className={styles['viewport']}>
        <PdfFrame
          src={pdfUrl}
          title={`${title} PDF`}
          onLoadError={() => setFailed(true)}
          className={cn(styles['frame'])}
        />
        {failed && (
          <div className={styles['placeholder']} role="alert">
            <EmptyState
              icon="warning"
              message="Couldn't load the preview"
              description="Open it in Paperless or download the original."
              action={
                <DocumentActions
                  pdfUrl={pdfUrl}
                  downloadFilename={downloadFilename}
                  paperlessUrl={paperlessUrl}
                />
              }
            />
          </div>
        )}
      </div>
    </Card>
  );
}
