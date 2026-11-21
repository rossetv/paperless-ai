import { cn } from '../../../lib/cn';
import styles from './NavBar.module.css';

export interface NavBarProps {
  /**
   * Brand / logo area, rendered on the leading edge of the nav.
   * Typically a logo mark, an app name, or an anchor wrapping either.
   */
  brand: React.ReactNode;
  /**
   * Optional links region between the brand and the actions, typically a row of
   * `<a>`/`<Link>` elements.
   */
  links?: React.ReactNode;
  /**
   * Actions area, rendered on the trailing edge of the nav.
   * Typically icon buttons, links, or a user-account control.
   */
  actions?: React.ReactNode;
  /** ARIA label for the <nav> landmark. Defaults to 'Main navigation'. */
  'aria-label'?: string;
  className?: string;
}

/**
 * Sticky application navigation bar with a frosted-glass backdrop.
 *
 * Slots: brand (leading), optional links, and actions (trailing).
 */
export function NavBar({
  brand,
  links,
  actions,
  'aria-label': ariaLabel = 'Main navigation',
  className,
}: NavBarProps): React.ReactElement {
  const navClasses = cn(styles['navbar'], className);

  return (
    <nav className={navClasses} aria-label={ariaLabel}>
      <div className={styles['inner']}>
        <div className={styles['brand']}>{brand}</div>
        {links !== undefined && (
          <div className={styles['links']} data-navbar-links>
            {links}
          </div>
        )}
        <div className={styles['spacer']} />
        {actions !== undefined && (
          <div className={styles['actions']}>{actions}</div>
        )}
      </div>
    </nav>
  );
}
