import stylesRaw from './Stack.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/** Flex direction of the stack. */
export type StackDirection = 'vertical' | 'horizontal';

/**
 * Gap between children; maps 1:1 to the --spacing-N tokens in tokens.css.
 * 1 = --spacing-1 (2px) … 14 = --spacing-14 (24px).
 */
export type StackGap = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14;

/** Cross-axis alignment (align-items). */
export type StackAlign = 'start' | 'center' | 'end' | 'stretch' | 'baseline';

/** Main-axis justification (justify-content). */
export type StackJustify = 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly';

export interface StackProps {
  /** Flex direction. Defaults to 'vertical'. */
  direction?: StackDirection;
  /**
   * Gap between children, mapped to the spacing token scale.
   * Omit for no gap.
   */
  gap?: StackGap;
  /** Cross-axis alignment. Omit to use the flexbox default (stretch). */
  align?: StackAlign;
  /** Main-axis justification. Omit to use the flexbox default (flex-start). */
  justify?: StackJustify;
  /** Whether children should wrap onto multiple lines. Defaults to false. */
  wrap?: boolean;
  /** Stack content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Flexbox stack primitive.
 *
 * Provides vertical (column) or horizontal (row) stacking with gap values
 * drawn from the design token spacing scale. Optional alignment and
 * justification props map to standard flexbox values.
 *
 * App-agnostic: knows nothing about search or documents.
 */
export function Stack({
  direction = 'vertical',
  gap,
  align,
  justify,
  wrap = false,
  children,
  className,
}: StackProps): React.ReactElement {
  const classes = [
    styles['stack'],
    styles[direction],
    gap !== undefined ? styles[`gap-${gap}`] : undefined,
    align !== undefined ? styles[`align-${align}`] : undefined,
    justify !== undefined ? styles[`justify-${justify}`] : undefined,
    wrap ? styles['wrap'] : styles['nowrap'],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <div className={classes}>{children}</div>;
}
