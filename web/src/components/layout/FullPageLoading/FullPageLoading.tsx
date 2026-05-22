import React from 'react';
import { Spinner } from '../../primitives/Spinner/Spinner';
import styles from './FullPageLoading.module.css';

/**
 * Full-viewport loading screen shown while bootstrap queries resolve.
 *
 * `role="status"` so assistive technology announces the wait. Uses the
 * `Spinner` primitive to convey activity.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3) — composes primitives only.
 */
export function FullPageLoading(): React.ReactElement {
  return (
    <div className={styles['root']}>
      <Spinner size="large" label="Loading…" />
    </div>
  );
}
