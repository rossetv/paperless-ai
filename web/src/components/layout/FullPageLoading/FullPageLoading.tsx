import React from 'react';
import { Spinner } from '../../primitives/Spinner/Spinner';
import styles from './FullPageLoading.module.css';

/** Full-viewport loading screen shown while bootstrap queries resolve. */
export function FullPageLoading(): React.ReactElement {
  return (
    <div className={styles['root']}>
      <Spinner size="large" label="Loading…" />
    </div>
  );
}
