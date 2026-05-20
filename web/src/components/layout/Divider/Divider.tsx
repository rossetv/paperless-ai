import { cn } from '../../../lib/cn';
import styles from './Divider.module.css';

/**
 * Divider orientation.
 * 'horizontal' (default) — a full-width rule separating stacked content.
 * 'vertical'             — a full-height rule separating inline content;
 *                          stretches to its flex container's height.
 */
export type DividerOrientation = 'horizontal' | 'vertical';

export interface DividerProps {
  /** Orientation of the rule. Defaults to 'horizontal'. */
  orientation?: DividerOrientation;
  /**
   * When true, the divider is purely decorative and carries
   * role="presentation" to hide it from assistive technology.
   * When false (default), it acts as a semantic separator.
   */
  decorative?: boolean;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Thin separator rule.
 *
 * Renders an <hr> styled as a hairline using the border token colour
 * (--colour-border). Supports both orientations: a horizontal rule between
 * stacked blocks, and a vertical rule between inline items (which stretches to
 * the height of its flex container).
 *
 * Follows Apple's sparse use of visible separators — use only where structural
 * separation is required, not for decoration.
 *
 * Set decorative={true} when the separator is purely visual and should be
 * hidden from screen readers. The <hr> implicit role is "separator"; for a
 * vertical divider aria-orientation is set so assistive tech announces it
 * correctly.
 *
 * App-agnostic: knows nothing about search or documents.
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
