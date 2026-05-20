import { cn } from '../../../lib/cn';
import styles from './Badge.module.css';

/**
 * Visual variant for the badge.
 *
 * DESIGN.md uses a single chromatic accent (Apple Blue) with no semantic
 * status colours. The two distinct visual treatments are:
 *   neutral — light-surface background, secondary text (low emphasis)
 *   accent  — Apple Blue background, on-dark text (high emphasis)
 *
 * Previous success/warning/danger variants were visually identical to
 * existing ones (success = accent, warning/danger used text-primary tones)
 * — a misleading API. They are removed to keep the API honest.
 */
export type BadgeVariant = 'neutral' | 'accent';

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
  const classes = cn(
    styles['badge'],
    styles[variant],
    className,
  );

  return (
    <span className={classes}>
      {children}
    </span>
  );
}
