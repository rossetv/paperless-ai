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
   * The parent (AnswerCard) uses this to highlight the source and open
   * its document preview.
   */
  onActivate: (index: number) => void;
  /**
   * Optional title of the cited source document — enriches the accessible
   * name from "View source N" to "View source N: <title>".
   */
  sourceTitle?: string | null;
}

/**
 * Inline citation marker rendered in the synthesised answer.
 *
 * Delegates rendering to the `CitationMark` primitive — a real, keyboard-
 * operable circular-chip `<button>` that exposes a "View source N" accessible
 * name. The parent wires `onActivate` to open the document preview and
 * highlight the matching source card.
 *
 * Composed from: CitationMark. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function CitationLink({
  index,
  onActivate,
  sourceTitle,
}: CitationLinkProps): React.ReactElement {
  return (
    <CitationMark index={index} onActivate={onActivate} sourceTitle={sourceTitle ?? null} />
  );
}
