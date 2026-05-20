import stylesRaw from './Grid.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/**
 * Number of equal-width columns.
 * Responsive: collapses to 1 column on mobile, capped at 2 on tablet.
 */
export type GridColumns = 1 | 2 | 3 | 4 | 5 | 6;

/**
 * Gap between grid cells; maps 1:1 to the --spacing-N tokens in tokens.css.
 * 1 = --spacing-1 (2px) … 14 = --spacing-14 (24px).
 */
export type GridGap = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14;

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
  const classes = [
    styles['grid'],
    styles[`columns-${columns}`],
    gap !== undefined ? styles[`gap-${gap}`] : undefined,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <div className={classes}>{children}</div>;
}
