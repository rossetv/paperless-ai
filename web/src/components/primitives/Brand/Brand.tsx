import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Brand.module.css';

export interface BrandProps {
  /**
   * Icon size in pixels. Controls both `width` and `height` of the SVG.
   * Defaults to 22 (the handoff artboard size).
   */
  size?: number;
  /**
   * Fill colour for the document sheets.
   * Defaults to `currentColor` so the mark inherits the surrounding text colour.
   */
  color?: string;
  /**
   * Accessible label. Supply to make the icon non-decorative (e.g. when it is
   * the only content in a link). Omit (or pass `undefined`) for decorative use —
   * the SVG will be `aria-hidden`.
   */
  'aria-label'?: string;
  /** Test hook. */
  'data-testid'?: string;
  /** Additional class names to merge onto the SVG element. */
  className?: string;
}

/**
 * Paperless AI brand mark.
 *
 * Two stacked document sheets with a small blue spark circle on the front
 * sheet's top-right corner — the geometric logo from the handoff artboard.
 *
 * The spark circle is always #0071e3 (--colour-accent); the sheets use the
 * `color` prop (defaults to `currentColor`) so the mark works on both light
 * and dark backgrounds without a `color` prop.
 *
 * Placement: render `Brand` inside a flex row alongside the wordmark span.
 * The `Brand` component renders the SVG only.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3).
 * Allowed deps: lib/ only.
 */
export function Brand({
  size = 22,
  color = 'currentColor',
  'aria-label': ariaLabel,
  'data-testid': testId,
  className,
}: BrandProps): React.ReactElement {
  const isDecorative = ariaLabel === undefined;
  const accessibilityProps = isDecorative
    ? ({ 'aria-hidden': 'true' } as const)
    : ({ role: 'img', 'aria-label': ariaLabel } as const);

  return (
    <svg
      viewBox="0 0 22 22"
      width={size}
      height={size}
      fill="none"
      className={cn(styles['brand'], className)}
      focusable="false"
      data-testid={testId}
      {...accessibilityProps}
    >
      {/* Back sheet — semi-opaque */}
      <rect x="3" y="2.5" width="11" height="14.5" rx="1.6" fill={color} fillOpacity="0.42" />
      {/* Front sheet — opaque */}
      <rect x="7" y="5" width="11" height="14.5" rx="1.6" fill={color} />
      {/* Spark notch — outer circle (accent blue, always) */}
      <circle cx="15.4" cy="7.6" r="1.4" fill="var(--colour-accent)" />
      {/* Spark notch — inner dot (white) */}
      <circle cx="15.4" cy="7.6" r="0.5" fill="var(--colour-text-on-dark)" />
    </svg>
  );
}
