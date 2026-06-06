import React from 'react';
import { cn } from '../../../lib/cn';
import { relativeTime } from '../../../lib/relativeTime';
import type { ReconcileCycle } from '../../../api/types';
import styles from './ActivityRow.module.css';

/** Format a summary count map as a compact human string — "+3 indexed · 1 failed". */
function formatSummary(summary: Record<string, number>): string {
  const parts = Object.entries(summary)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => `${count} ${key}`);
  return parts.length > 0 ? parts.join(' · ') : '';
}

export interface ActivityRowProps {
  /** One reconcile cycle, from GET /api/index/activity. */
  cycle: ReconcileCycle;
  /** When true the bottom divider is dropped (the last row in a list). */
  last?: boolean;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * One entry in the reconcile-activity history.
 *
 * A leading status dot (ok/error tone), a relative `started_at` time, the
 * cycle `kind` + `detail` label, and a compact summary of counts. The `ok`
 * flag drives the dot colour.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — takes a domain wire type.
 */
export function ActivityRow({
  cycle,
  last = false,
  className,
}: ActivityRowProps): React.ReactElement {
  const dotClass = styles[cycle.ok ? 'ok' : 'error'];
  const summaryText = formatSummary(cycle.summary);

  return (
    <div className={cn(styles['row'], last && styles['last'], className)}>
      <span
        className={cn(styles['dot'], dotClass)}
        data-testid="activity-dot"
        aria-hidden="true"
      />
      <time className={styles['time']} dateTime={cycle.started_at}>
        {relativeTime(cycle.started_at)}
      </time>
      <div>
        <div className={styles['label']}>
          {cycle.kind === 'sweep' ? 'Deletion sweep' : 'Reconcile cycle'}{' '}
          {cycle.ok ? 'complete' : 'failed'}
        </div>
        <div className={styles['detail']}>
          {cycle.detail}
          {summaryText !== '' && ` · ${summaryText}`}
        </div>
      </div>
    </div>
  );
}
