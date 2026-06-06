import React from 'react';
import { cn } from '../../../lib/cn';
import { Button } from '../../../components/primitives/Button/Button';
import styles from './SaveBar.module.css';

export interface SaveBarProps {
  /** Number of fields with unsaved changes. Hidden when this is zero. */
  dirtyCount: number;
  /** True while the save mutation is in-flight. */
  isPending: boolean;
  /** Called when the user clicks Discard. */
  onDiscard: () => void;
  /** Called when the user clicks Save. */
  onSave: () => void;
}

/**
 * Sticky bottom glass bar that slides up when there are unsaved settings.
 *
 * Hidden via the `.bar-hidden` CSS class (translateY(100%)) when
 * `dirtyCount === 0`; slides in when dirty. Shows a warning dot, an
 * unsaved-changes count, a caption, and Discard / Save buttons.
 *
 * The bar element carries `aria-live="polite"` and `aria-atomic="true"` so
 * screen readers announce the unsaved-changes count when it changes.
 * `aria-hidden={isHidden}` suppresses announcements when the bar is off-screen.
 *
 * Tier: features/settings — composes primitives, no domain knowledge beyond
 * the unsaved-count contract.
 */
export function SaveBar({
  dirtyCount,
  isPending,
  onDiscard,
  onSave,
}: SaveBarProps): React.ReactElement {
  const isHidden = dirtyCount === 0;
  return (
    <div
      className={cn(styles['bar'], isHidden && styles['bar-hidden'])}
      aria-hidden={isHidden}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className={styles['inner']}>
        <span className={styles['dot']} aria-hidden="true" />
        <span className={styles['message']}>
          {dirtyCount} unsaved {dirtyCount === 1 ? 'change' : 'changes'}
        </span>
        <span className={styles['caption']}>
          Daemons hot-load saved settings — no restart needed
        </span>
        <Button
          variant="secondary"
          size="small"
          disabled={isPending}
          onClick={onDiscard}
        >
          Discard
        </Button>
        <Button
          variant="primary"
          size="small"
          disabled={isPending}
          onClick={onSave}
        >
          {isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </div>
  );
}
