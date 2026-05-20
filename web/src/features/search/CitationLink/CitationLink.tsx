import { Button } from '../../../components/primitives/Button/Button';

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
 * Inline citation marker rendered as [n].
 *
 * A real <button> (via the Button primitive) so it is keyboard operable
 * and participates in the tab order. A visually-hidden span appends
 * "Citation n" to the accessible name so screen readers announce the purpose
 * rather than just announcing "[n]".
 *
 * The parent is responsible for wiring the onActivate handler to the
 * corresponding SourceCard (e.g. scrolling it into view or highlighting it).
 *
 * No own CSS module — visual form comes entirely from the Button primitive.
 * The screen-reader-only text uses the canonical `.visually-hidden` utility
 * class from `styles/global.css`; the features layer carries no styling of its
 * own (§12.5), and there is exactly one definition of the visually-hidden
 * technique in the codebase.
 */
export function CitationLink({ index, onActivate }: CitationLinkProps): React.ReactElement {
  return (
    <Button
      variant="secondary"
      size="small"
      onClick={() => onActivate(index)}
    >
      <span aria-hidden="true">[{index}]</span>
      <span className="visually-hidden">Citation {index}</span>
    </Button>
  );
}
