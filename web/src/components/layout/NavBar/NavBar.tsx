import stylesRaw from './NavBar.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

export interface NavBarProps {
  /**
   * Brand / logo area, rendered on the leading edge of the nav.
   * Typically a logo mark, an app name, or an anchor wrapping either.
   */
  brand: React.ReactNode;
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
 * Exposes two named slots: brand (leading) and actions (trailing). The inner
 * layout is a flexbox row with space-between, so the two slots sit at opposite
 * ends of the nav.
 *
 * Keyboard-navigable: renders a semantic <nav> landmark with an ARIA label;
 * interactive children receive focus in DOM order via Tab. No custom focus
 * management is applied here — the nav's children own their own focus behaviour.
 */
export function NavBar({
  brand,
  actions,
  'aria-label': ariaLabel = 'Main navigation',
  className,
}: NavBarProps): React.ReactElement {
  const navClasses = [styles['navbar'], className].filter(Boolean).join(' ');

  return (
    <nav className={navClasses} aria-label={ariaLabel}>
      <div className={styles['inner']}>
        <div className={styles['brand']}>{brand}</div>
        {actions !== undefined && (
          <div className={styles['actions']}>{actions}</div>
        )}
      </div>
    </nav>
  );
}
