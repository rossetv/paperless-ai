import { cn } from '../../../lib/cn';
import type { SpacingScale } from '../spacing';
import gapStyles from '../gap.module.css';
import styles from './Grid.module.css';

/** Number of equal-width columns. */
export type GridColumns = 1 | 2 | 3 | 4 | 5 | 6;

/** Gap between grid cells, on the spacing scale shared with Stack. */
export type GridGap = SpacingScale;

export interface GridProps {
  /** Number of equal-width columns. Not responsive: pass the count for the viewport. */
  columns: GridColumns;
  /** Gap between cells on the spacing token scale. Omit for no gap. */
  gap?: GridGap;
  children: React.ReactNode;
  className?: string;
}

/** CSS grid with equal-width columns and token-based gaps. */
export function Grid({ columns, gap, children, className }: GridProps): React.ReactElement {
  const classes = cn(
    styles['grid'],
    styles[`columns-${columns}`],
    gap !== undefined ? gapStyles[`gap-${gap}`] : undefined,
    className,
  );

  return <div className={classes}>{children}</div>;
}
