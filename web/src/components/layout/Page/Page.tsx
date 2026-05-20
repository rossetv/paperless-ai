import stylesRaw from './Page.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface PageProps {
  /** Page content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Top-level page wrapper.
 *
 * Sets the page background (--colour-bg) and enforces a minimum height of the
 * full viewport. All pages must be wrapped in Page — it is the outermost layout
 * primitive. It does not centre or constrain content; use Container for that.
 *
 * App-agnostic: knows nothing about search or documents.
 */
export function Page({ children, className }: PageProps): React.ReactElement {
  const classes = [styles['page'], className].filter(Boolean).join(' ');

  return <div className={classes}>{children}</div>;
}
