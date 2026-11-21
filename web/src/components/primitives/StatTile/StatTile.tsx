import type React from 'react';
import { cn } from '../../../lib/cn';
import styles from './StatTile.module.css';

export interface StatTileProps {
  /** The headline figure — a number, or a pre-formatted string. */
  value: number | string;
  /** The uppercase label above the figure. */
  label: string;
  /** Optional caption sub-line below the figure. */
  sub?: string;
  /** When true the figure is rendered in the accent colour. */
  accent?: boolean;
  className?: string;
}

/** Small statistic tile: an uppercase label, a large figure and an optional sub-line. */
export function StatTile({
  value,
  label,
  sub,
  accent = false,
  className,
}: StatTileProps): React.ReactElement {
  return (
    <div className={cn(styles['tile'], className)}>
      <span className={styles['label']}>{label}</span>
      <span
        className={cn(styles['value'], accent && styles['accent'])}
        data-testid="stat-tile-value"
      >
        {value}
      </span>
      {sub !== undefined && (
        <span className={styles['sub']} data-testid="stat-tile-sub">
          {sub}
        </span>
      )}
    </div>
  );
}
