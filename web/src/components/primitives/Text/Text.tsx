import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Text.module.css';

/**
 * Typographic variant — each maps to one step of the SF Pro type scale
 * (DESIGN.md §3). Choosing a variant is choosing a reviewed type token, not
 * an ad-hoc font size.
 */
export type TextVariant =
  | 'body'
  | 'body-emphasis'
  | 'card-title'
  | 'caption'
  | 'caption-bold'
  | 'micro';

/** Colour tone — overrides the variant's default text colour role. */
export type TextTone = 'primary' | 'secondary' | 'tertiary';

/**
 * HTML element the text renders as. A closed set: running text is a `p`,
 * an inline run is a `span`, an emphasised inline run is `strong`/`em`, and a
 * machine-readable date is a `time`.
 */
export type TextElement = 'p' | 'span' | 'strong' | 'em' | 'time' | 'div';

export interface TextProps {
  /** Typographic variant — maps to the type scale. Defaults to 'body'. */
  variant?: TextVariant;
  /** HTML element to render. Defaults to 'p'. */
  as?: TextElement;
  /**
   * Colour tone. Omit to use the variant's default role (body → primary,
   * caption → secondary, micro → tertiary).
   */
  tone?: TextTone;
  /**
   * Machine-readable datetime — only meaningful when `as="time"`, where it
   * becomes the `dateTime` attribute so assistive tech can parse the date.
   */
  dateTime?: string;
  /** Text content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/** Maps a tone to its modifier class; the variant default needs no class. */
function toneClass(tone: TextTone | undefined): string | undefined {
  if (tone === 'secondary') return styles['tone-secondary'];
  if (tone === 'tertiary') return styles['tone-tertiary'];
  return undefined;
}

/**
 * The typography primitive.
 *
 * Renders text at one step of the design-system type scale. Every piece of
 * text in the application flows through `Text` (or another styled component)
 * so the type scale is applied deliberately — features no longer render raw
 * `<p>`/`<span>`/`<strong>` and inherit typography from global element CSS.
 *
 * Polymorphic via `as`: a paragraph, an inline span, an emphasised run, or a
 * `<time>` element. App-agnostic — knows nothing about the domain.
 */
export function Text({
  variant = 'body',
  as: Element = 'p',
  tone,
  dateTime,
  children,
  className,
}: TextProps): React.ReactElement {
  const classes = cn(styles['text'], styles[variant], toneClass(tone), className);

  // `dateTime` is only a valid attribute on <time>; spread it conditionally so
  // it never lands on a <p>/<span> under exactOptionalPropertyTypes.
  const timeProps =
    Element === 'time' && dateTime !== undefined ? { dateTime } : {};

  return (
    <Element className={classes} {...timeProps}>
      {children}
    </Element>
  );
}
