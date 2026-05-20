import stylesRaw from './Divider.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface DividerProps {
  /**
   * When true, the divider is purely decorative and carries
   * role="presentation" to hide it from assistive technology.
   * When false (default), it acts as a semantic separator.
   */
  decorative?: boolean;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Thin horizontal rule.
 *
 * Renders an <hr> element styled as a 1px line using the border token colour
 * (--colour-border). Follows Apple's sparse use of visible separators —
 * use only where structural separation is required, not for decoration.
 *
 * Set decorative={true} when the separator is purely visual and should be
 * hidden from screen readers.
 *
 * App-agnostic: knows nothing about search or documents.
 */
export function Divider({ decorative = false, className }: DividerProps): React.ReactElement {
  const classes = [styles['divider'], styles['horizontal'], className].filter(Boolean).join(' ');

  return (
    <hr
      className={classes}
      role={decorative ? 'presentation' : undefined}
      aria-hidden={decorative ? true : undefined}
    />
  );
}
