import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Avatar.module.css';

export interface AvatarProps {
  /**
   * The 1–2 character initials to display.
   * Callers are responsible for deriving initials from `display_name` or
   * `username` — this component does no string processing.
   */
  initials: string;
  /**
   * Background colour as a CSS colour string or gradient.
   * In the handoff: `linear-gradient(135deg,#5e6166,#2a2a2d)` for the generic
   * user-menu avatar; per-user colours in the Users table.
   * Callers pick a colour; this component just applies it.
   */
  colour: string;
  /**
   * Diameter in pixels. Controls width, height, and font-size proportionally
   * (font-size ≈ size × 0.42 — matches the handoff formula).
   * Defaults to 30 px.
   */
  size?: number;
  /** Test hook. */
  'data-testid'?: string;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * Circular initials avatar.
 *
 * Renders a coloured circle with centred initials. The `colour` prop may be
 * any CSS colour string, including gradients. Font size scales proportionally
 * with `size` using the formula `size × 0.42` (source: handoff `settings.jsx`
 * line 720). Background and dimensions are applied inline because they are
 * dynamic; all other styling uses the CSS module and tokens.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3).
 * Allowed deps: lib/ only.
 */
export function Avatar({
  initials,
  colour,
  size = 30,
  'data-testid': testId,
  className,
}: AvatarProps): React.ReactElement {
  return (
    <div
      className={cn(styles['avatar'], className)}
      style={{
        width: size,
        height: size,
        background: colour,
        fontSize: Math.round(size * 0.42),
      }}
      data-testid={testId}
    >
      {initials}
    </div>
  );
}
