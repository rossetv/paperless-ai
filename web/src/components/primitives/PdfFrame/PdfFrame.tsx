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
 * Security: the upstream is pinned to `Content-Type: application/pdf` with
 * `X-Content-Type-Options: nosniff` by the backend (`document_routes.py`),
 * so a malicious `.html`/`.svg` in the Paperless library cannot be served as
 * active content into this iframe. An empty `sandbox=""` was previously
 * applied as defence in depth, but Chrome's native PDF viewer refuses to
 * render under a fully-locked sandbox — the iframe paints blank. Removing
 * the attribute restores rendering; the `nosniff` + pinned content-type
 * already prevents the active-content vector this sandbox was guarding
 * against (CODE_GUIDELINES §10).
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
      />
    </div>
  );
}
