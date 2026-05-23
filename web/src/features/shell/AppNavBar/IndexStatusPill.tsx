import React from 'react';
import { useStats } from '../../../api/hooks';
import styles from './AppNavBar.module.css';

/**
 * Compact index-status indicator for the navigation bar.
 *
 * Shows a green ready dot followed by "index ready · N docs". Reads from the
 * `useStats` query — renders nothing while loading or on error so the nav
 * never shows stale or missing data.
 *
 * Presentational data flows entirely from the query; no props are required.
 * The pill always renders regardless of nav variant — it is a persistent
 * system-health signal, not a per-screen affordance.
 *
 * Tier: features/shell (CODE_GUIDELINES §12.3). Allowed deps: api/hooks, lib/.
 */
export function IndexStatusPill(): React.ReactElement | null {
  const stats = useStats();

  if (!stats.isSuccess || stats.data === undefined) {
    return null;
  }

  const docCount = stats.data.document_count.toLocaleString('en-GB');

  return (
    <span className={styles['pill']} aria-label={`Index ready, ${docCount} documents`}>
      <span className={styles['pill-dot']} aria-hidden="true" />
      index ready · {docCount} docs
    </span>
  );
}
