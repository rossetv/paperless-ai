import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './CitationMark.module.css';

export interface CitationMarkProps {
  /** 1-based citation index — matches the [n] markers in the answer text. */
  index: number;
  /**
   * Called with the index when the mark is activated (click or keyboard).
   * Optional — omit at display-only call sites where no scroll-to-source
   * behaviour is needed (e.g. the document preview sidebar).
   */
  onActivate?: (index: number) => void;
  /**
   * Optional document title for the cited source. When provided, the
   * accessible name becomes "View source N: <title>" instead of "View source N".
   */
  sourceTitle?: string | null;
  className?: string;
}

/**
 * Inline numbered citation chip in the answer prose. Always a `<button>`, even
 * without `onActivate`, for visual consistency.
 */
export function CitationMark({
  index,
  onActivate,
  sourceTitle,
  className,
}: CitationMarkProps): React.ReactElement {
  const accessibleName =
    sourceTitle != null
      ? `View source ${index}: ${sourceTitle}`
      : `View source ${index}`;

  return (
    <button
      type="button"
      aria-label={accessibleName}
      className={cn(styles['citation-mark'], className)}
      onClick={() => onActivate?.(index)}
    >
      <span aria-hidden="true">{index}</span>
    </button>
  );
}
