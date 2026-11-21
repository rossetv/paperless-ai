import { cn } from '../../../lib/cn';
import styles from './Divider.module.css';

/** 'vertical' stretches to the height of its flex container. */
export type DividerOrientation = 'horizontal' | 'vertical';

export interface DividerProps {
  /** Orientation of the rule. Defaults to 'horizontal'. */
  orientation?: DividerOrientation;
  /** Hide from assistive technology when the rule is purely visual. */
  decorative?: boolean;
  className?: string;
}

/**
 * Thin separator rule rendered as an `<hr>`. Vertical dividers set
 * aria-orientation so assistive tech announces them correctly.
 */
export function Divider({
  orientation = 'horizontal',
  decorative = false,
  className,
}: DividerProps): React.ReactElement {
  const classes = cn(styles['divider'], styles[orientation], className);

  return (
    <hr
      className={classes}
      role={decorative ? 'presentation' : undefined}
      aria-hidden={decorative ? true : undefined}
      aria-orientation={
        !decorative && orientation === 'vertical' ? 'vertical' : undefined
      }
    />
  );
}
