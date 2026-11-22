import React, { useRef, useEffect } from 'react';
import { cn } from '../../../lib/cn';
import { Button } from '../../../components/primitives/Button/Button';
import styles from './SaveBar.module.css';

export interface SaveBarProps {
  /** Number of fields with unsaved changes. Hidden when this is zero. */
  dirtyCount: number;
  isPending: boolean;
  onDiscard: () => void;
  onSave: () => void;
  /**
   * At least one changed key requires a full search-index rebuild; the caption becomes an amber
   * warning that saving will re-embed the whole library.
   */
  reindexPending?: boolean;
}

/**
 * Sticky bottom glass bar that slides up when there are unsaved settings.
 *
 * `aria-live` announces the unsaved count as it changes. When hidden, `inert` removes the
 * buttons from the tab order and silences them for assistive tech; `aria-hidden` is deliberately
 * not used, as WAI-ARIA forbids it on containers with focusable descendants.
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

  // `inert` is not in stable @types/react; setting it imperatively avoids an `any` cast and the
  // experimental types import.
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
    <>
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
          <span className={cn(styles['caption'], reindexPending && styles['caption-reindex'])}>
            {reindexPending
              ? 'Saving rebuilds the search index — every document will be re-embedded.'
              : 'Daemons hot-load saved settings — no restart needed'}
          </span>
          <Button variant="secondary" size="small" disabled={isPending} onClick={onDiscard}>
            Discard
          </Button>
          <Button variant="primary" size="small" disabled={isPending} onClick={onSave}>
            {isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </div>
      <div className={cn(styles['spacer'], isHidden && styles['spacer-hidden'])} aria-hidden="true" />
    </>
  );
}
