import { cn } from '../../../lib/cn';
import type { SpacingScale } from '../spacing';
import gapStyles from '../gap.module.css';
import styles from './Stack.module.css';

export type StackDirection = 'vertical' | 'horizontal';

/** Gap between children, on the spacing scale shared with Grid. */
export type StackGap = SpacingScale;

/** Cross-axis alignment (align-items). */
export type StackAlign = 'start' | 'center' | 'end' | 'stretch' | 'baseline';

/** Main-axis justification (justify-content). */
export type StackJustify = 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly';

export interface StackProps {
  /** Flex direction. Defaults to 'vertical'. */
  direction?: StackDirection;
  /** Gap between children on the spacing token scale. Omit for no gap. */
  gap?: StackGap;
  /** Cross-axis alignment. Omit to use the flexbox default (stretch). */
  align?: StackAlign;
  /** Main-axis justification. Omit to use the flexbox default (flex-start). */
  justify?: StackJustify;
  /** Whether children should wrap onto multiple lines. Defaults to false. */
  wrap?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Flexbox stack with gaps from the spacing token scale. */
export function Stack({
  direction = 'vertical',
  gap,
  align,
  justify,
  wrap = false,
  children,
  className,
}: StackProps): React.ReactElement {
  const classes = cn(
    styles['stack'],
    styles[direction],
    gap !== undefined ? gapStyles[`gap-${gap}`] : undefined,
    align !== undefined ? styles[`align-${align}`] : undefined,
    justify !== undefined ? styles[`justify-${justify}`] : undefined,
    wrap ? styles['wrap'] : styles['nowrap'],
    className,
  );

  return <div className={classes}>{children}</div>;
}
