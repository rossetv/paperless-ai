import stylesRaw from './Section.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface SectionProps {
  /**
   * When true, applies generous vertical padding for full cinematic section
   * treatment (DESIGN.md §5). Default padding is compact, suitable for
   * sub-sections within a page.
   */
  spacious?: boolean;
  /** Section content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Content section providing consistent vertical rhythm.
 *
 * Renders a semantic <section> element with vertical padding from the spacing
 * scale. The spacious prop applies the full "cinematic breathing room" padding
 * described in DESIGN.md §5 — used for top-level page sections that each
 * occupy roughly one viewport height.
 *
 * App-agnostic: knows nothing about search or documents.
 */
export function Section({ spacious = false, children, className }: SectionProps): React.ReactElement {
  const classes = [
    styles['section'],
    spacious ? styles['spacious'] : undefined,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <section className={classes}>{children}</section>;
}
