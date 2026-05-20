import { cn } from '../../../lib/cn';
import styles from './Container.module.css';

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
  const classes = cn(styles['container'], className);

  return <div className={classes}>{children}</div>;
}
