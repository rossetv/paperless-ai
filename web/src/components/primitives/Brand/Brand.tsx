import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Brand.module.css';

export interface BrandProps {
  /** Width and height in pixels. Defaults to 22. */
  size?: number;
  /**
   * Fill colour for the document sheets.
   * Defaults to `currentColor` so the mark inherits the surrounding text colour.
   */
  colour?: string;
  /**
   * Accessible label. Supply to make the icon non-decorative (e.g. when it is
   * the only content in a link). Omit (or pass `undefined`) for decorative use —
   * the SVG will be `aria-hidden`.
   */
  'aria-label'?: string;
  'data-testid'?: string;
  className?: string;
}

/**
 * Paperless AI brand mark: two stacked document sheets with an accent spark.
 *
 * The sheets use `colour` (default `currentColor`) so the mark works on light
 * and dark backgrounds; the spark is always the accent colour. Renders the SVG
 * only; place the wordmark beside it.
 */
export function Brand({
  size = 22,
  colour = 'currentColor',
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
      <rect x="3" y="2.5" width="11" height="14.5" rx="1.6" fill={colour} fillOpacity="0.42" />
      {/* Front sheet — opaque */}
      <rect x="7" y="5" width="11" height="14.5" rx="1.6" fill={colour} />
      {/* Spark notch — outer circle (accent blue, always) */}
      <circle cx="15.4" cy="7.6" r="1.4" fill="var(--colour-accent)" />
      {/* Spark notch — inner dot (white) */}
      <circle cx="15.4" cy="7.6" r="0.5" fill="var(--colour-text-on-dark)" />
    </svg>
  );
}
