import React from 'react';
import { cn } from '../../../lib/cn';
import type { ReconcileCycle } from '../../../api/types';
import styles from './ActivityRow.module.css';

/**
 * Render an ISO-8601 timestamp as a short relative phrase.
 *
 * `null` → "now"; under a minute (or any future time, i.e. clock skew) →
 * "now"; otherwise the largest whole unit — "4m ago", "3h ago", "2d ago".
 * `now` is injectable so the unit test is deterministic; production passes
 * the real current time.
 */
export function relativeTime(at: string | null, now: Date = new Date()): string {
  if (at === null) {
    return 'now';
  }
  const deltaMs = now.getTime() - new Date(at).getTime();
  if (deltaMs < 60_000) {
    return 'now';
  }
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  return `${Math.floor(hours / 24)}d ago`;
}

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
