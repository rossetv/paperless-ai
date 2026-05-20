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

/**
 * Closed width set — proportions of the container. A skeleton never accepts a
 * free CSS length: its width is one of these named fractions so every loading
 * placeholder reads consistently.
 *   'full'   — 100%   'wide' — 75%   'half' — 50%   'narrow' — 33%
 */
export type SkeletonWidth = 'full' | 'wide' | 'half' | 'narrow';

/**
 * Closed height set — each maps to a dedicated token in tokens.css. A skeleton
 * never accepts a free CSS length; its height is a named, token-backed size.
 *   'line'    — one line of caption-scale text   (--height-skeleton-line)
 *   'control' — a form control: Input, Select    (--height-skeleton-control)
 *   'block'   — a small content block            (--height-skeleton-block)
 *   'media'   — an image / thumbnail placeholder (--height-skeleton-media)
 */
export type SkeletonHeight = 'line' | 'control' | 'block' | 'media';

export interface SkeletonProps {
  /** Shape of the placeholder. Defaults to 'rectangular'. */
  variant?: SkeletonVariant;
  /**
   * Number of text lines to render. Only meaningful for the 'text' variant;
   * each line is a separate bar and the last is shortened for realism.
   * Defaults to 1. Ignored for 'rectangular' and 'circular'.
   */
  lines?: number;
  /**
   * Width as a named fraction of the container. When omitted, the skeleton
   * fills its container's width ('full').
   */
  width?: SkeletonWidth;
  /**
   * Height as a named, token-backed size. When omitted, the variant's default
   * height from the CSS module applies.
   */
  height?: SkeletonHeight;
  /** Additional class names to merge. */
  className?: string;
}

/** Builds the merged class list for a single skeleton bar. */
function barClasses(
  variant: SkeletonVariant,
  width: SkeletonWidth | undefined,
  height: SkeletonHeight | undefined,
  className: string | undefined,
): string {
  return [
    styles['skeleton'],
    styles[variant],
    width !== undefined ? styles[`width-${width}`] : undefined,
    height !== undefined ? styles[`height-${height}`] : undefined,
    className,
  ]
    .filter(Boolean)
    .join(' ');
}

/**
 * Content-placeholder block for loading states.
 *
 * Purely decorative — aria-hidden="true" so screen readers skip it.
 * The shimmer animation respects prefers-reduced-motion: it is disabled
 * when the user has requested reduced motion, leaving a static placeholder.
 *
 * Sizing is a closed, token-backed API: `width` is a named fraction and
 * `height` maps to a dedicated token. There is no free-string length prop —
 * a skeleton's dimensions always come from tokens.css (§12.4).
 */
export function Skeleton({
  variant = 'rectangular',
  lines = 1,
  width,
  height,
  className,
}: SkeletonProps): React.ReactElement {
  // Multi-line text: render a stack of bars; shorten the final line so the
  // block reads like a real paragraph rather than a solid rectangle.
  if (variant === 'text' && lines > 1) {
    return (
      <span aria-hidden="true" className={styles['lines']}>
        {Array.from({ length: lines }, (_, index) => {
          const isLast = index === lines - 1;
          const lineWidth: SkeletonWidth | undefined = isLast ? 'wide' : width;
          return (
            <span
              key={index}
              className={barClasses('text', lineWidth, height, className)}
            />
          );
        })}
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      className={barClasses(variant, width, height, className)}
    />
  );
}
