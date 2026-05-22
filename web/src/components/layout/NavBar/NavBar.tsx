import { cn } from '../../../lib/cn';
import styles from './NavBar.module.css';

export interface NavBarProps {
  /**
   * Brand / logo area, rendered on the leading edge of the nav.
   * Typically a logo mark, an app name, or an anchor wrapping either.
   */
  brand: React.ReactNode;
  /**
   * Optional centre navigation-links region, rendered after the brand and
   * before the actions. Typically a row of `<a>`/`<Link>` elements. When
   * omitted, the bar is a simple brand-left / actions-right layout — existing
   * usage is unaffected.
   */
  links?: React.ReactNode;
  /**
   * Actions area, rendered on the trailing edge of the nav.
   * Typically icon buttons, links, or a user-account control.
   */
  actions?: React.ReactNode;
  /**
   * ARIA label for the <nav> landmark.
   * Defaults to 'Main navigation'. Override when multiple navs are on the page.
   */
  'aria-label'?: string;
  /** Additional class names to merge onto the <nav> element. */
  className?: string;
}

/**
 * Application navigation bar with the glass-navigation treatment.
 *
 * Implements the frosted translucent backdrop from DESIGN.md §4 and §6:
 *   - Sticky, floats above scrolling content
 *   - Background: rgba(0,0,0,0.8) + backdrop-filter: saturate(180%) blur(20px)
 *   - Height: 48px (--height-nav)
 *   - Text: white, 12px SF Pro Text
 *
 * Exposes three named slots: brand (leading), optional links (centre-left),
 * and actions (trailing). The inner layout is a flexbox row; a flexible
 * spacer between the links and the actions pushes the actions to the trailing
 * edge, so omitting `links` yields the original brand-left / actions-right
 * layout unchanged.
 *
 * Keyboard-navigable: renders a semantic <nav> landmark with an ARIA label;
 * interactive children receive focus in DOM order via Tab. No custom focus
 * management is applied here — the nav's children own their own focus behaviour.
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
        {/* Spacer pushes the actions to the trailing edge. With no links the
            brand sits left and actions right exactly as before. */}
        <div className={styles['spacer']} />
        {actions !== undefined && (
          <div className={styles['actions']}>{actions}</div>
        )}
      </div>
    </nav>
  );
}
