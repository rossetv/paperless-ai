import stylesRaw from './Badge.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/**
 * Semantic colour variant for the badge.
 *
 * All variants use only design-system tokens — no custom colours.
 * DESIGN.md only documents two clear accent-vs-neutral roles;
 * success/warning/danger are mapped to the same token vocabulary by convention:
 * success = accent (the only chromatic colour), warning/danger = text-tertiary/text-primary.
 * This interpretation is documented here because DESIGN.md does not address
 * semantic status colours explicitly — Apple's system uses a single blue accent.
 */
export type BadgeVariant = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export interface BadgeProps {
  /** Semantic colour variant. Defaults to 'neutral'. */
  variant?: BadgeVariant;
  /** Badge content — typically a short string or number. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Small inline status/count label.
 *
 * Renders as a <span> so it sits naturally in flowing text or flex layouts.
 * Reads all design values from CSS tokens — no hardcoded colours or sizes.
 * Not interactive; does not need a focus ring.
 */
export function Badge({
  variant = 'neutral',
  children,
  className,
}: BadgeProps): React.ReactElement {
  const classes = [
    styles['badge'],
    styles[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes}>
      {children}
    </span>
  );
}
