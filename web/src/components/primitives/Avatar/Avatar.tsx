import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Avatar.module.css';

export interface AvatarProps {
  /**
   * The 1–2 character initials to display. Callers derive them; this component
   * does no string processing.
   */
  initials: string;
  /** Background as any CSS colour or gradient. */
  colour: string;
  /** Diameter in pixels; the font size scales at size × 0.42. Defaults to 30. */
  size?: number;
  'data-testid'?: string;
  className?: string;
}

/** Circular initials avatar. Colour and dimensions are inline because they vary per use. */
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
