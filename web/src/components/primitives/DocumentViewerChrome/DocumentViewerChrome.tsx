import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './DocumentViewerChrome.module.css';

export interface DocumentViewerChromeProps {
  /** The document title — shown in the breadcrumb. */
  title: string;
  /** The Paperless document URL — the "Open in Paperless" link target. */
  paperlessUrl: string;
  /**
   * The PDF download URL — the "Download" link target. When omitted, the
   * Download action is not rendered.
   */
  downloadUrl?: string;
  /** Called when the close control is activated. */
  onClose: () => void;
  /** The page area — the PDF iframe. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The in-app PDF viewer shell.
 *
 * A forced-dark top bar — a close control, a "Search results › title"
 * breadcrumb, and Download / Open-in-Paperless actions — above the page area
 * supplied as `children`, matching the handoff's dedicated viewer chrome.
 *
 * Dark in both themes. Most surfaces and text use the forced-dark
 * `--colour-dark-*` tokens (theme-independent by definition). The bar
 * background, the control-hover fill and the focus ring additionally use
 * `--colour-nav-bg`, `--colour-hover-dark` and `--colour-focus-ring`: those
 * are `--colour-*` roles, but each is declared to the *same* value in both
 * the light `:root` and the dark theme, so the shell stays dark regardless
 * of the active theme.
 *
 * App-agnostic: it knows a title and two URLs, nothing about the document
 * API. The `DocumentPreviewScreen` feature supplies the page iframe.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function DocumentViewerChrome({
  title,
  paperlessUrl,
  downloadUrl,
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
          <span className={styles['crumb-context']}>Search results</span>
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
              download
            >
              <Icon name="document" size="small" />
              Download
            </a>
          )}
          <a
            className={styles['action']}
            href={paperlessUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in Paperless
            <Icon name="external-link" size="small" />
          </a>
        </span>
      </div>

      <div className={styles['page-area']}>{children}</div>
    </div>
  );
}
