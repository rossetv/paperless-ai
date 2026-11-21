import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './DocumentViewerChrome.module.css';

export interface DocumentViewerChromeProps {
  /** The document title — shown in the breadcrumb after the separator. */
  title: string;
  /** Context label at the start of the breadcrumb. Defaults to "Search results". */
  breadcrumbLabel?: string;
  /**
   * The "Open in Paperless" link target. When absent, null or empty the action is
   * not rendered (the Library preview has no deep link).
   */
  paperlessUrl?: string | null;
  /**
   * The PDF download URL — the "Download" link target. When omitted, the
   * Download action is not rendered.
   */
  downloadUrl?: string;
  /**
   * Suggested filename for the download (sets the `download` attribute). Ignored
   * without `downloadUrl`.
   */
  downloadFilename?: string;
  /** Extra toolbar actions, e.g. elements styled with the shared `action` class. */
  extraActions?: React.ReactNode;
  /** Called when the close control is activated. */
  onClose: () => void;
  /** The page area — the PDF iframe. */
  children: React.ReactNode;
  className?: string;
}

/**
 * In-app PDF viewer shell: a top bar (close, breadcrumb, Download and Open in
 * Paperless) above the page area supplied as `children`. Dark in both themes.
 */
export function DocumentViewerChrome({
  title,
  breadcrumbLabel = 'Search results',
  paperlessUrl,
  downloadUrl,
  downloadFilename,
  extraActions,
  onClose,
  children,
  className,
}: DocumentViewerChromeProps): React.ReactElement {
  return (
    <div className={cn(styles['chrome'], className)}>
      <div className={styles['bar']}>
        <button
          type="button"
          className={styles['close']}
          onClick={onClose}
          aria-label="Close document preview"
        >
          <Icon name="close" size="small" />
        </button>

        <span className={styles['crumb']}>
          <span className={styles['crumb-context']}>{breadcrumbLabel}</span>
          <span className={styles['crumb-context']} aria-hidden="true">
            ›
          </span>
          <span className={styles['crumb-title']}>{title}</span>
        </span>

        <span className={styles['spacer']} />

        <span className={styles['actions']}>
          {downloadUrl !== undefined && (
            <a
              className={styles['action']}
              href={downloadUrl}
              download={downloadFilename ?? true}
            >
              <Icon name="document" size="small" />
              Download
            </a>
          )}
          {paperlessUrl != null && paperlessUrl !== '' && (
            <a
              className={styles['action']}
              href={paperlessUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in Paperless
              <Icon name="external-link" size="small" />
            </a>
          )}
          {extraActions}
        </span>
      </div>

      <div className={styles['page-area']}>{children}</div>
    </div>
  );
}
