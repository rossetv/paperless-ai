import stylesRaw from './Container.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface ContainerProps {
  /** Container content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Horizontally-centred, max-width content container.
 *
 * Constrains content to --width-content-max (980px) and centres it with
 * auto margins. Adds horizontal padding so content never touches the viewport
 * edge on narrow viewports.
 *
 * Composes with Page (outer) and Section (inner): Page → Container → Section.
 * App-agnostic: knows nothing about search or documents.
 */
export function Container({ children, className }: ContainerProps): React.ReactElement {
  const classes = [styles['container'], className].filter(Boolean).join(' ');

  return <div className={classes}>{children}</div>;
}
