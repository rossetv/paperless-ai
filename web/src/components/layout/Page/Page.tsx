import { cn } from '../../../lib/cn';
import styles from './Page.module.css';

export interface PageProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Outermost page wrapper: sets the page background and a full-viewport minimum
 * height. Does not constrain width; use Container for that.
 */
export function Page({ children, className }: PageProps): React.ReactElement {
  const classes = cn(styles['page'], className);

  return <div className={classes}>{children}</div>;
}
