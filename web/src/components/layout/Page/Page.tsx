import { cn } from '../../../lib/cn';
import styles from './Page.module.css';

export interface PageProps {
  /** Navigation bars, rendered above the main landmark rather than inside it. */
  nav?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/**
 * Outermost page wrapper: sets the page background and a full-viewport minimum
 * height, and holds the children in the page's one `<main>` landmark.
 * Does not constrain width; use Container for that.
 */
export function Page({ nav, children, className }: PageProps): React.ReactElement {
  const classes = cn(styles['page'], className);

  return (
    <div className={classes}>
      {nav}
      <main>{children}</main>
    </div>
  );
}
