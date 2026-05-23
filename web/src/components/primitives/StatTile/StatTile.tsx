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
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * A small statistic tile — an uppercase label, a large figure, an optional
 * sub-line.
 *
 * Presentational and domain-agnostic. Used in the Index dashboard stat row.
 * The `accent` flag tints the figure with the accent colour for the single
 * "headline" metric in a row.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
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
