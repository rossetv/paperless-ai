import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './DocumentViewerChrome.module.css';

export interface DocumentViewerChromeProps {
  /** The document title — shown in the breadcrumb after the separator. */
  title: string;
  /**
   * Context label shown at the start of the breadcrumb (e.g. "Search results",
   * "Documents"). Defaults to "Search results" to preserve existing behaviour.
   * Pass a custom value to reuse the chrome in other screens (FE-22).
   */
  breadcrumbLabel?: string;
  /**
   * The Paperless document URL — the "Open in Paperless" link target.
   *
   * When absent, null, or an empty string, the "Open in Paperless" action is
   * not rendered.  The Library preview does not carry a deep-link URL; the
   * prop is optional so the chrome handles both contexts cleanly.
   */
  paperlessUrl?: string | null;
  /**
   * The PDF download URL — the "Download" link target. When omitted, the
   * Download action is not rendered.
   */
  downloadUrl?: string;
  /**
   * Optional extra actions rendered in the action row alongside Download and
   * Open-in-Paperless. Pass an array of rendered elements (e.g. anchor or
   * button styled with the shared `action` class) so callers (FE-B8) can
   * extend the toolbar without duplicating the chrome.
   */
  extraActions?: React.ReactNode;
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
 * A forced-dark top bar — a close control, a configurable breadcrumb, and
 * Download / Open-in-Paperless actions — above the page area supplied as
 * `children`, matching the handoff's dedicated viewer chrome.
 *
 * Dark in both themes. Most surfaces and text use the forced-dark
 * `--colour-dark-*` tokens (theme-independent by definition). The bar
 * background, the control-hover fill and the focus ring additionally use
 * `--colour-nav-bg`, `--colour-hover-dark` and `--colour-focus-ring`: those
 * are `--colour-*` roles, but each is declared to the *same* value in both
 * the light `:root` and the dark theme, so the shell stays dark regardless
 * of the active theme.
 *
 * Generic: `breadcrumbLabel` sets the context segment (default "Search
 * results") so the chrome can be reused by the document feature without
 * hard-coding the search context (FE-22). `extraActions` extends the action
 * row for callers that need additional toolbar controls (FE-B8).
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function DocumentViewerChrome({
  title,
  breadcrumbLabel = 'Search results',
  paperlessUrl,
  downloadUrl,
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
              download
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
