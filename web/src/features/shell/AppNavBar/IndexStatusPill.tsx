import React from 'react';
import { useStats } from '../../../api/hooks';
import styles from './AppNavBar.module.css';

/** "index ready · N docs" pill for the nav bar; renders nothing while loading or on error. */
export function IndexStatusPill(): React.ReactElement | null {
  const stats = useStats();

  if (!stats.isSuccess || stats.data === undefined) {
    return null;
  }

  const docCount = stats.data.document_count.toLocaleString('en-GB');

  return (
    <span className={styles['pill']} role="status" aria-label={`Index ready, ${docCount} documents`}>
      <span className={styles['pill-dot']} aria-hidden="true" />
      index ready · {docCount} docs
    </span>
  );
}
