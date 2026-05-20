import stylesRaw from './Skeleton.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/**
 * Shape variant for the skeleton placeholder.
 * 'text'        — short, rounded pill shape for inline text lines.
 * 'rectangular' — block shape for images, cards, or generic areas.
 * 'circular'    — circle for avatars or icons.
 */
export type SkeletonVariant = 'text' | 'rectangular' | 'circular';

export interface SkeletonProps {
  /** Shape of the placeholder. Defaults to 'rectangular'. */
  variant?: SkeletonVariant;
  /**
   * Explicit width. Accepts any valid CSS length (e.g. '200px', '100%').
   * When omitted, the skeleton fills its container's width.
   */
  width?: string;
  /**
   * Explicit height. Accepts any valid CSS length.
   * When omitted, uses the variant's default height from the CSS module.
   */
  height?: string;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Content-placeholder block for loading states.
 *
 * Purely decorative — aria-hidden="true" so screen readers skip it.
 * The shimmer animation respects prefers-reduced-motion: it is disabled
 * when the user has requested reduced motion, leaving a static placeholder.
 */
export function Skeleton({
  variant = 'rectangular',
  width,
  height,
  className,
}: SkeletonProps): React.ReactElement {
  const classes = [
    styles['skeleton'],
    styles[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const inlineStyle: React.CSSProperties = {};
  if (width !== undefined) inlineStyle.width = width;
  if (height !== undefined) inlineStyle.height = height;

  return (
    <span
      aria-hidden="true"
      className={classes}
      style={Object.keys(inlineStyle).length > 0 ? inlineStyle : undefined}
    />
  );
}
