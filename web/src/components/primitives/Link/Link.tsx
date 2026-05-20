import { cn } from '../../../lib/cn';
import styles from './Link.module.css';

/**
 * Visual variant — default is the standard light-bg link style.
 * - 'default': --colour-link on light backgrounds.
 * - 'inline':  underlined inline body link.
 * - 'on-dark': --colour-link-on-dark for use on dark/black backgrounds.
 */
export type LinkVariant = 'default' | 'inline' | 'on-dark';

export interface LinkProps {
  /** Destination URL. */
  href: string;
  /** Visual treatment. Defaults to 'default'. */
  variant?: LinkVariant;
  /**
   * When true, the link opens in a new tab and gets rel="noopener noreferrer"
   * for security (prevents the new tab accessing window.opener).
   */
  external?: boolean;
  /** Click handler — e.g. to preventDefault on SPA navigation. */
  onClick?: React.MouseEventHandler<HTMLAnchorElement>;
  /** Link label content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Generic primitive anchor link.
 *
 * Uses a semantic <a> element with full keyboard accessibility.
 * Reads all design values from CSS tokens — no hardcoded colours or sizes.
 * Three variants: default (light-bg), inline (body text), on-dark (dark-bg).
 *
 * When `external` is true, target="_blank" is set together with
 * rel="noopener noreferrer" to prevent the opened page from accessing
 * the opener's browsing context — a security requirement for external links.
 */
export function Link({
  href,
  variant = 'default',
  external = false,
  onClick,
  children,
  className,
}: LinkProps): React.ReactElement {
  const classes = cn(
    styles['link'],
    styles[variant],
    className,
  );

  return (
    <a
      href={href}
      target={external ? '_blank' : undefined}
      rel={external ? 'noopener noreferrer' : undefined}
      onClick={onClick}
      className={classes}
    >
      {children}
    </a>
  );
}
