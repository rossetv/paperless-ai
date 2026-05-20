import { cn } from '../../../lib/cn';
import styles from './Card.module.css';

/**
 * Surface colour of the card.
 * 'default' — the light surface (--colour-surface).
 * 'dark'    — the dark "section" surface (--colour-surface-dark), for a dark
 *             band card on a light page (DESIGN.md §2).
 */
export type CardSurface = 'default' | 'dark';

/** Allowed HTML container elements. */
export type CardElement = 'div' | 'article' | 'section' | 'aside';

export interface CardProps {
  /**
   * HTML element to render as the card container.
   * Use 'article' for self-contained content, 'section' for a thematic group,
   * 'div' (default) when semantics are provided by the content.
   */
  as?: CardElement;
  /**
   * Surface colour — controls the background token.
   * 'default' = light surface; 'dark' = the dark-section surface.
   */
  surface?: CardSurface;
  /**
   * When true, applies the single Apple card shadow (--shadow-card).
   * Leave false for flat cards embedded within an already-elevated surface.
   */
  elevated?: boolean;
  /** Card content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Surface container with the DESIGN.md card treatment.
 *
 * Applies radius (--radius-standard, 8px), padding from tokens, and
 * optionally the single diffused card shadow.
 *
 * Card knows nothing about the domain — it is a generic layout surface.
 * Semantic content hierarchy is supplied by the caller via the `as` prop
 * and by the children.
 *
 * Card itself is not interactive; no focus ring is applied here.
 */
export function Card({
  as: Element = 'div',
  surface = 'default',
  elevated = false,
  children,
  className,
}: CardProps): React.ReactElement {
  const classes = cn(
    styles['card'],
    styles[surface],
    elevated ? styles['elevated'] : undefined,
    className,
  );

  return (
    <Element className={classes}>
      {children}
    </Element>
  );
}
