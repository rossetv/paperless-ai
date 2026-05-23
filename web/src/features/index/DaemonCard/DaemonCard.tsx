import React from 'react';
import { cn } from '../../../lib/cn';
import { StatusBadge } from '../../../components/primitives/StatusBadge/StatusBadge';
import type { StatusTone } from '../../../components/primitives/StatusBadge/StatusBadge';
import { relativeTime } from '../ActivityRow/ActivityRow';
import type { DaemonStatus, DaemonState } from '../../../api/types';
import styles from './DaemonCard.module.css';

/** Maps a daemon run-state to a StatusBadge tone and label. */
const STATE_PRESENTATION: Record<DaemonState, { tone: StatusTone; label: string }> = {
  running: { tone: 'ok', label: 'Running' },
  idle: { tone: 'warn', label: 'Idle' },
  stopped: { tone: 'danger', label: 'Stopped' },
};

export interface DaemonCardProps {
  /** The daemon's status, from GET /api/index/status. */
  daemon: DaemonStatus;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * A status card for one worker daemon.
 *
 * Shows the daemon name, a `StatusBadge` for its run-state, the daemon's
 * `detail` sentence, its cumulative `processed_count`, and a relative
 * "last seen" time derived from `last_heartbeat`. The run-state drives the
 * badge tone via `STATE_PRESENTATION`.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — composes the StatusBadge
 * primitive, reuses `relativeTime` from ActivityRow, and takes a domain
 * wire type.
 */
export function DaemonCard({ daemon, className }: DaemonCardProps): React.ReactElement {
  const { tone, label } = STATE_PRESENTATION[daemon.state];

  return (
    <article className={cn(styles['card'], className)}>
      <div className={styles['header']}>
        <span className={styles['name']}>{daemon.name}</span>
        <span className={styles['spacer']} />
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </div>
      <div className={styles['metrics']}>
        <span className={styles['detail']}>{daemon.detail}</span>
        <span className={styles['throughput']}>
          {daemon.processed_count.toLocaleString('en-GB')} processed
        </span>
      </div>
      <p className={styles['role']}>
        Last seen {relativeTime(daemon.last_heartbeat)}
      </p>
    </article>
  );
}
