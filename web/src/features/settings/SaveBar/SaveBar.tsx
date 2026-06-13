import React, { useRef, useEffect } from 'react';
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
  /**
   * When true, at least one changed key requires a full search-index rebuild.
   * The caption swaps to an amber warning so the operator knows saving will
   * re-embed the whole library.
   */
  reindexPending?: boolean;
}

/**
 * Sticky bottom glass bar that slides up when there are unsaved settings.
 *
 * Hidden via the `.bar-hidden` CSS class (translateY(100%) + visibility:hidden)
 * when `dirtyCount === 0`; slides in when dirty. Shows a warning dot, an
 * unsaved-changes count, a caption, and Discard / Save buttons.
 *
 * The bar element carries `aria-live="polite"` and `aria-atomic="true"` so
 * screen readers announce the unsaved-changes count when it changes.
 * When hidden, the `inert` property (set imperatively via ref — not a React
 * prop, as `inert` is only in @types/react experimental) removes all
 * descendants from the tab order and suppresses AT announcements.
 * `aria-hidden` is intentionally absent — WAI-ARIA §6.6 forbids it on
 * containers that hold focusable descendants.
 *
 * Tier: features/settings — composes primitives, no domain knowledge beyond
 * the unsaved-count contract.
 */
export function SaveBar({
  dirtyCount,
  isPending,
  onDiscard,
  onSave,
  reindexPending = false,
}: SaveBarProps): React.ReactElement {
  const isHidden = dirtyCount === 0;
  const barRef = useRef<HTMLDivElement>(null);

  // `inert` is a DOM property not yet in stable @types/react — set it
  // imperatively so we avoid both `any` casts and the experimental import.
  useEffect(() => {
    const el = barRef.current;
    if (el === null) return;
    if (isHidden) {
      el.setAttribute('inert', '');
    } else {
      el.removeAttribute('inert');
    }
  }, [isHidden]);

  return (
    <div
      ref={barRef}
      className={cn(styles['bar'], isHidden && styles['bar-hidden'])}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className={styles['inner']}>
        <span className={styles['dot']} aria-hidden="true" />
        <span className={styles['message']}>
          {dirtyCount} unsaved {dirtyCount === 1 ? 'change' : 'changes'}
        </span>
        <span
          className={cn(
            styles['caption'],
            reindexPending && styles['caption-reindex'],
          )}
        >
          {reindexPending
            ? 'Saving rebuilds the search index — every document will be re-embedded.'
            : 'Daemons hot-load saved settings — no restart needed'}
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
