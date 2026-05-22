import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './StatCard.module.css';

export interface StatCardProps {
  /** The headline figure — a number, or a string for a placeholder dash. */
  value: number | string;
  /** The lower-case caption beneath the figure. */
  label: string;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * A small statistic card — one large figure above a caption.
 *
 * Presentational only. Used in the access-control screens' stat rows.
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function StatCard({
  value,
  label,
  className,
}: StatCardProps): React.ReactElement {
  return (
    <div className={cn(styles['card'], className)}>
      <div className={styles['value']}>{value}</div>
      <div className={styles['label']}>{label}</div>
    </div>
  );
}
