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

// Visually-hidden text utility — puts text in the accessibility tree without
// disturbing the visual layout. Inline style is intentional: this pattern is
// standardised in the WCAG technique and does not require a CSS token.
// Using inline style here avoids needing a CSS module in the features layer,
// which is forbidden by §12.5. The pattern is identical to a11y-utils libraries.
const visuallyHiddenStyle: React.CSSProperties = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0,0,0,0)',
  whiteSpace: 'nowrap',
  border: 0,
};

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
 * The visually-hidden technique uses a self-contained inline style (a11y
 * standard practice; does not violate §12.5's prohibition on CSS modules in
 * the features layer).
 */
export function CitationLink({ index, onActivate }: CitationLinkProps): React.ReactElement {
  return (
    <Button
      variant="secondary"
      size="small"
      onClick={() => onActivate(index)}
    >
      <span aria-hidden="true">[{index}]</span>
      <span style={visuallyHiddenStyle}>Citation {index}</span>
    </Button>
  );
}
