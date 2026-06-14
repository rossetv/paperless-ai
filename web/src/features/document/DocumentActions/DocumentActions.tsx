import React from 'react';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Link } from '../../../components/primitives/Link/Link';
import { cn } from '../../../lib/cn';
import styles from './DocumentActions.module.css';

export interface DocumentActionsProps {
  /** Proxied PDF stream URL — the Download anchor's href. */
  pdfUrl: string;
  /**
   * Suggested filename for the Download anchor (sets the `download` attribute
   * so the browser names the file rather than deriving "pdf.pdf" from the URL).
   */
  downloadFilename: string;
  /**
   * Full Paperless-ngx URL for the document detail page. When null the
   * "Open in Paperless" action is omitted.
   */
  paperlessUrl: string | null;
  /** Additional class names to merge onto the row. */
  className?: string;
}

/**
 * The document-level action row: Download (in-app, primary) and Open in
 * Paperless (external, demoted to a quiet inline link — UI-24 / DD-3).
 *
 * Rendered as a horizontal row under the document title, and reused as the
 * escape hatches inside the PDF viewer's load-error state. Extracted so both
 * call sites share one definition rather than duplicating the markup.
 *
 * Tier: features/document (CODE_GUIDELINES §12.3). Imports from components/* only.
 */
export function DocumentActions({
  pdfUrl,
  downloadFilename,
  paperlessUrl,
  className,
}: DocumentActionsProps): React.ReactElement {
  return (
    <div className={cn(styles['actions'], className)}>
      <a className={styles['action']} href={pdfUrl} download={downloadFilename}>
        <Icon name="document" size="small" />
        Download
      </a>
      {paperlessUrl !== null && (
        <Link href={paperlessUrl} external className={cn(styles['external-action'])}>
          <Icon name="external-link" size="small" />
          Open in Paperless
        </Link>
      )}
    </div>
  );
}
