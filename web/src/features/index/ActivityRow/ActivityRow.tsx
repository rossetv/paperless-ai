import { cn } from '../../../lib/cn';
import type { ActivityEntry, ActivityStatus } from '../../../api/types';
import styles from './ActivityRow.module.css';

/** Maps an activity status to its dot CSS-module class name. */
const STATUS_DOT_CLASS: Record<ActivityStatus, string> = {
  ok: 'ok',
  warn: 'warn',
  idle: 'info',
  error: 'error',
};

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

export interface ActivityRowProps {
  /** The activity entry, from GET /api/index/activity. */
  entry: ActivityEntry;
  /** When true the bottom divider is dropped (the last row in a list). */
  last?: boolean;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * One entry in the reconcile-activity history.
 *
 * A leading status dot, a relative time, and a label + detail pair. The
 * status drives the dot colour; the timestamp is rendered as a relative
 * phrase inside a `<time>` element carrying the machine-readable value.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — takes a domain wire type.
 */
export function ActivityRow({
  entry,
  last = false,
  className,
}: ActivityRowProps): React.ReactElement {
  const dotClass = styles[STATUS_DOT_CLASS[entry.status]];

  return (
    <div className={cn(styles['row'], last && styles['last'], className)}>
      <span
        className={cn(styles['dot'], dotClass)}
        data-testid="activity-dot"
        aria-hidden="true"
      />
      {entry.at !== null ? (
        <time className={styles['time']} dateTime={entry.at}>
          {relativeTime(entry.at)}
        </time>
      ) : (
        <span className={styles['time']}>now</span>
      )}
      <div>
        <div className={styles['label']}>{entry.label}</div>
        <div className={styles['detail']}>{entry.detail}</div>
      </div>
    </div>
  );
}
