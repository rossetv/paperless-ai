import { cn } from '../../../lib/cn';
import styles from './Card.module.css';

export type CardSurface = 'default' | 'dark';

export type CardElement = 'div' | 'article' | 'section' | 'aside';

export interface CardProps {
  /**
   * HTML element to render as the card container.
   * Use 'article' for self-contained content, 'section' for a thematic group,
   * 'div' (default) when semantics are provided by the content.
   */
  as?: CardElement;
  /**
   * Background surface: the light default, or the dark "section" surface for a
   * dark band on a light page.
   */
  surface?: CardSurface;
  /** Applies the card shadow. Leave false for flat cards inside an already-elevated surface. */
  elevated?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Generic surface container with the standard card radius, padding and optional shadow. */
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
