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
  /**
   * Called once when the embedded PDF fails to load — either the iframe fires
   * an `error` event, or it never fires `load` within the grace window (a
   * refused-framing or stalled stream paints the browser's grey error box, not
   * an `error` event, so a timeout is the only reliable signal). The caller
   * renders its own app-owned fallback over the frame.
   */
  onLoadError?: () => void;
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/**
 * Grace window before a frame that has not fired `load` is treated as failed.
 *
 * A refused-framing response or a stalled proxy stream never fires `load` *or*
 * `error` — the iframe just shows the browser's grey "refused to connect" box.
 * The timeout is the only signal that distinguishes "still loading" from
 * "wedged", so the caller can swap in an app-owned error state. Eight seconds
 * is long enough that a slow-but-healthy first paint is not misreported.
 */
const LOAD_TIMEOUT_MS = 8000;

/**
 * An embedded PDF viewport.
 *
 * Renders the PDF in an `<iframe>` on a dark backdrop; the browser's built-in
 * PDF viewer handles rendering, page navigation and zoom. Keeping it an
 * `<iframe>` of the proxied stream is the simplest correct approach — no
 * `pdf.js` bundle, no extra dependency (web-redesign §5).
 *
 * Failure detection: the browser paints its own grey error placeholder for a
 * 4xx/5xx, a refused-framing response, or a stalled stream, and that box covers
 * any backdrop drawn *behind* the iframe. So the frame reports failure up via
 * `onLoadError` (an `error` event, or no `load` within `LOAD_TIMEOUT_MS`) and
 * the caller paints an app-owned dark error state *over* the frame — the user
 * never sees the bare browser box. A successful `load` cancels the timeout.
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
  onLoadError,
  className,
}: PdfFrameProps): React.ReactElement {
  // `loadedRef` latches once the iframe fires `load`, cancelling the timeout
  // and suppressing any further failure report. `reportedRef` makes failure a
  // one-shot per src so the caller's fallback is reported at most once.
  const loadedRef = React.useRef(false);
  const reportedRef = React.useRef(false);

  // Hold the latest callback in a ref so `reportFailure` stays stable across
  // renders: the caller typically passes an inline `onLoadError`, and a
  // changing dependency would re-arm the timeout on every parent re-render,
  // preventing it from ever firing.
  const onLoadErrorRef = React.useRef(onLoadError);
  onLoadErrorRef.current = onLoadError;

  const reportFailure = React.useCallback((): void => {
    if (loadedRef.current || reportedRef.current) return;
    reportedRef.current = true;
    onLoadErrorRef.current?.();
  }, []);

  // Reset the latches and arm the load timeout whenever the source changes, so
  // a fresh document gets a fresh chance to load before being judged failed.
  React.useEffect(() => {
    loadedRef.current = false;
    reportedRef.current = false;
    const timer = window.setTimeout(reportFailure, LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [src, reportFailure]);

  return (
    <div className={cn(styles['wrapper'], className)}>
      <iframe
        className={styles['frame']}
        src={src}
        title={title}
        onLoad={() => {
          loadedRef.current = true;
        }}
        onError={reportFailure}
      />
    </div>
  );
}
