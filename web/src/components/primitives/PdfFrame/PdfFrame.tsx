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
   * Called once when the PDF fails to load: on an `error` event, or when `load`
   * has not fired within LOAD_TIMEOUT_MS. The caller renders its own fallback
   * over the frame.
   */
  onLoadError?: () => void;
  className?: string;
}

/**
 * Grace window before a frame that has not fired `load` counts as failed. A
 * refused-framing response or stalled stream fires neither `load` nor `error`,
 * so a timeout is the only signal; 8 s avoids misreporting a slow first paint.
 */
const LOAD_TIMEOUT_MS = 8000;

/**
 * An embedded PDF, rendered by the browser's built-in viewer in an `<iframe>`.
 *
 * The browser's grey error box would cover any backdrop drawn behind the frame,
 * so failures are reported through `onLoadError` and the caller paints its own
 * error state over the frame.
 *
 * No `sandbox` attribute: Chrome's PDF viewer paints blank under a fully locked
 * sandbox. The backend pins `Content-Type: application/pdf` with
 * `X-Content-Type-Options: nosniff` (src/search/document_routes/_proxy.py), so a
 * malicious `.html`/`.svg` cannot be served as active content into this frame.
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
