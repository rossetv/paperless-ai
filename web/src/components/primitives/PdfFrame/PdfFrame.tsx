import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './PdfFrame.module.css';

export interface PdfFrameProps {
  /** The PDF URL — typically the in-app `documentPdfUrl(id)` proxy path. */
  src: string;
  /**
   * Accessible title for the iframe — assistive tech announces it, so it
   * should name the document (e.g. its title).
   */
  title: string;
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/**
 * An embedded PDF viewport.
 *
 * Renders the PDF in an `<iframe>` on a dark backdrop; the browser's built-in
 * PDF viewer handles rendering, page navigation and zoom. Keeping it an
 * `<iframe>` of the proxied stream is the simplest correct approach — no
 * `pdf.js` bundle, no extra dependency (web-redesign §5).
 *
 * The iframe carries an empty `sandbox` — the most restrictive value, no
 * `allow-scripts`, no `allow-same-origin`. The `src` is same-origin with the
 * app, so if the proxied resource were ever served as active content (a
 * malicious `.html`/`.svg` in the Paperless library) the sandbox denies it
 * script execution and same-origin access. A PDF needs neither — the
 * browser's native PDF viewer is browser-privileged, not page script — so
 * the empty sandbox does not break rendering. Defence in depth on top of the
 * proxy pinning `Content-Type: application/pdf` with `nosniff`
 * (CODE_GUIDELINES §10).
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function PdfFrame({
  src,
  title,
  className,
}: PdfFrameProps): React.ReactElement {
  return (
    <div className={cn(styles['wrapper'], className)}>
      <iframe
        className={styles['frame']}
        src={src}
        title={title}
        sandbox=""
      />
    </div>
  );
}
