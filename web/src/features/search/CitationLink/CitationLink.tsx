import React from 'react';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';

export interface CitationLinkProps {
  /**
   * 1-based citation index matching the [n] markers in the answer text
   * and the corresponding source in SourceDocument[].
   */
  index: number;
  /**
   * Called with the citation index when the user activates the link.
   * The parent (AnswerCard) uses this to highlight / scroll to the source.
   */
  onActivate: (index: number) => void;
}

/**
 * Inline citation marker rendered in the synthesised answer.
 *
 * Delegates rendering to the `CitationMark` primitive — a real, keyboard-
 * operable circular-chip `<button>` that exposes a "Citation n" accessible
 * name. The parent wires `onActivate` to scroll/highlight the matching source.
 *
 * Composed from: CitationMark. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function CitationLink({
  index,
  onActivate,
}: CitationLinkProps): React.ReactElement {
  return <CitationMark index={index} onActivate={onActivate} />;
}
