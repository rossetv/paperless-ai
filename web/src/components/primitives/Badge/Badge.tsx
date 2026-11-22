import { cn } from '../../../lib/cn';
import styles from './Badge.module.css';

/** 'neutral' is low emphasis; 'accent' is high emphasis. */
export type BadgeVariant = 'neutral' | 'accent';

export interface BadgeProps {
  /** Semantic colour variant. Defaults to 'neutral'. */
  variant?: BadgeVariant;
  /** Badge content — typically a short string or number. */
  children: React.ReactNode;
  className?: string;
  /** Tooltip with the full text, for a label that may be truncated. */
  title?: string;
}

/**
 * Small inline label for generic counts and tags.
 *
 * RoleBadge, StatusBadge and ScopePill are separate primitives because each
 * carries domain knowledge (label maps, a status dot) that does not belong here.
 */
export function Badge({
  variant = 'neutral',
  children,
  className,
  title,
}: BadgeProps): React.ReactElement {
  const classes = cn(
    styles['badge'],
    styles[variant],
    className,
  );

  return (
    <span className={classes} title={title}>
      <span className={styles['label']}>{children}</span>
    </span>
  );
}
