import { cn } from '../../../lib/cn';
import type { SpacingScale } from '../spacing';
import styles from './Grid.module.css';

/**
 * Number of equal-width columns.
 * Responsive: collapses to 1 column on mobile, capped at 2 on tablet.
 */
export type GridColumns = 1 | 2 | 3 | 4 | 5 | 6;

/**
 * Gap between grid cells; a step on the shared spacing-token scale.
 * Re-exported as an alias of `SpacingScale` so the gap scale has one
 * definition shared with Stack.
 */
export type GridGap = SpacingScale;

export interface GridProps {
  /**
   * Number of equal-width columns (1–6). Required.
   * Multi-column grids are automatically responsive: they collapse to 1 column
   * below 640px and cap at 2 columns between 640px and 834px.
   */
  columns: GridColumns;
  /**
   * Gap between cells, mapped to the spacing token scale.
   * Omit for no gap.
   */
  gap?: GridGap;
  /** Grid content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * CSS grid with equal-width columns and token-based gaps.
 *
 * Responsive out of the box: multi-column grids collapse to a single column on
 * mobile viewports (<640px) and cap at two columns on tablet (<834px).
 *
 * App-agnostic: knows nothing about search or documents.
 */
export function Grid({ columns, gap, children, className }: GridProps): React.ReactElement {
  const classes = cn(
    styles['grid'],
    styles[`columns-${columns}`],
    gap !== undefined ? styles[`gap-${gap}`] : undefined,
    className,
  );

  return <div className={classes}>{children}</div>;
}
