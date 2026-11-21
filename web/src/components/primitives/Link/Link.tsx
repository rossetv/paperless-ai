import { cn } from '../../../lib/cn';
import styles from './Link.module.css';

/**
 * - 'default': --colour-link on light backgrounds.
 * - 'inline': body-copy link, distinguished by colour alone (no underline).
 * - 'on-dark': --colour-link-on-dark for dark backgrounds.
 */
export type LinkVariant = 'default' | 'inline' | 'on-dark';

export interface LinkProps {
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
  children: React.ReactNode;
  className?: string;
}

/** Generic anchor link. External links open in a new tab with rel="noopener noreferrer". */
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
