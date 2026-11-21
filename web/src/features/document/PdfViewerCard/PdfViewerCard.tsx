import React from 'react';
import { documentPdfUrl } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { PdfFrame } from '../../../components/primitives/PdfFrame/PdfFrame';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { DocumentActions } from '../DocumentActions/DocumentActions';
import { cn } from '../../../lib/cn';
import styles from './PdfViewerCard.module.css';

export interface PdfViewerCardProps {
  documentId: number;
  /** Used for the iframe's accessible title. */
  title: string;
  /** Paperless-ngx document page; null omits "Open in Paperless". */
  paperlessUrl: string | null;
  /** Without it the browser names the file "pdf.pdf" from the proxy URL. */
  downloadFilename: string;
}

/**
 * Card that embeds the PDF viewer for one document; pager and zoom come from
 * the browser's native PDF chrome.
 *
 * When the frame reports a load failure (4xx/5xx proxy response, refused
 * framing, stalled stream), a dark error state with the `DocumentActions`
 * escape hatches covers it, so the user never sees the browser's grey error box.
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
