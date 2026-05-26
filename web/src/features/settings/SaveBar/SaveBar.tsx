import React from 'react';
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
 * Hidden via `transform: translateY(100%)` when `dirtyCount === 0`; slides in
 * when dirty. Shows a warning dot, an unsaved-changes count, a caption, and
 * Discard / Save buttons.
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
      className={styles['bar']}
      style={{ transform: isHidden ? 'translateY(100%)' : 'translateY(0)' }}
      aria-hidden={isHidden}
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
