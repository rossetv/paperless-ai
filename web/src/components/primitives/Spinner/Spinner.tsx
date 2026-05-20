import stylesRaw from './Spinner.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/** Size scale for the spinner ring. */
export type SpinnerSize = 'small' | 'medium' | 'large';

export interface SpinnerProps {
  /**
   * Accessible label announced to screen readers.
   * Defaults to "Loading…" — override for context-specific messages.
   */
  label?: string;
  /** Size of the spinner ring. Defaults to 'medium'. */
  size?: SpinnerSize;
  /** Additional class names to merge onto the wrapper element. */
  className?: string;
}

/**
 * Accessible CSS-animated loading indicator.
 *
 * Uses role="status" so screen readers announce the label as a live region
 * without interrupting the user. The label text is visually hidden but present
 * in the accessibility tree.
 *
 * The spin animation respects prefers-reduced-motion: the rotation is replaced
 * with a simple opacity pulse that conveys "activity" without vestibular risk.
 */
export function Spinner({
  label = 'Loading…',
  size = 'medium',
  className,
}: SpinnerProps): React.ReactElement {
  const classes = [
    styles['spinner'],
    styles[size],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span role="status" aria-label={label} className={classes}>
      <span className={styles['ring']} aria-hidden="true" />
      <span className={styles['sr-only']}>{label}</span>
    </span>
  );
}
