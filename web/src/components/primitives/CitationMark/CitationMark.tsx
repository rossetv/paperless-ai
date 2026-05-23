import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './CitationMark.module.css';

export interface CitationMarkProps {
  /** 1-based citation index — matches the [n] markers in the answer text. */
  index: number;
  /** Called with the index when the mark is activated (click or keyboard). */
  onActivate: (index: number) => void;
  /**
   * Optional document title for the cited source. When provided, the
   * accessible name becomes "View source N: <title>" instead of "View source N".
   */
  sourceTitle?: string | null;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Inline citation chip — a small accent circle carrying a numeral.
 *
 * A real `<button>` so it is keyboard-operable and tab-reachable. The
 * accessible name is "View source N" (with an optional title suffix when the
 * source title is known). Rendered inline in the synthesised-answer prose; the
 * parent wires `onActivate` to open the document preview and highlight the
 * corresponding source card.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
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
      onClick={() => onActivate(index)}
    >
      <span aria-hidden="true">{index}</span>
    </button>
  );
}
