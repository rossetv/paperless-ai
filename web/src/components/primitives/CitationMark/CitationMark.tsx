import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './CitationMark.module.css';

export interface CitationMarkProps {
  /** 1-based citation index — matches the [n] markers in the answer text. */
  index: number;
  /** Called with the index when the mark is activated (click or keyboard). */
  onActivate: (index: number) => void;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Inline citation chip — a small accent circle carrying a numeral.
 *
 * A real `<button>` so it is keyboard-operable and tab-reachable. A
 * visually-hidden suffix gives screen readers "Citation n" rather than a bare
 * number. Rendered inline in the synthesised-answer prose; the parent wires
 * `onActivate` to scroll/highlight the matching source.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function CitationMark({
  index,
  onActivate,
  className,
}: CitationMarkProps): React.ReactElement {
  return (
    <button
      type="button"
      className={cn(styles['citation-mark'], className)}
      onClick={() => onActivate(index)}
    >
      <span aria-hidden="true">{index}</span>
      <span className="visually-hidden">Citation {index}</span>
    </button>
  );
}
