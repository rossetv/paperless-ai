import React from 'react';
import { cn } from '../../../lib/cn';
import type { IndexHealthStatus } from '../../../api/types';
import styles from './IndexHealthHero.module.css';

/** Human-readable label and tone for each health verdict. */
const HEALTH_PRESENTATION: Record<
  IndexHealthStatus,
  { headline: string; detail: string; healthy: boolean }
> = {
  ok: {
    headline: 'Healthy · ready to serve',
    detail: 'All daemons running and heartbeating within the stale window.',
    healthy: true,
  },
  degraded: {
    headline: 'Degraded · some daemons stopped',
    detail: 'One or more daemons have missed their heartbeat window.',
    healthy: false,
  },
  down: {
    headline: 'Down · no daemons running',
    detail: 'All daemons have missed their heartbeat window or the index is unreadable.',
    healthy: false,
  },
};

/** Tick glyph for the healthy state. */
function TickIcon(): React.ReactElement {
  return (
    <svg
      viewBox="0 0 32 32"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="8,16 14,22 24,10" />
    </svg>
  );
}

/** Warning-triangle glyph for the unhealthy state. */
function WarningIcon(): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 4l9 16H3z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <circle cx="12" cy="17" r="0.8" fill="currentColor" />
    </svg>
  );
}

export interface IndexHealthHeroProps {
  /** The overall index health verdict, from GET /api/index/status. */
  health: IndexHealthStatus;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * The Index dashboard health hero.
 *
 * A circular status icon (tick when ok, warning triangle otherwise), a
 * "Status" eyebrow + headline + detail. The icon tint and glyph flip on the
 * `"ok"` verdict; `"degraded"` and `"down"` both use the unhealthy tone.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — takes a domain wire type.
 */
export function IndexHealthHero({
  health,
  className,
}: IndexHealthHeroProps): React.ReactElement {
  const { headline, detail, healthy } = HEALTH_PRESENTATION[health];

  return (
    <section className={cn(styles['hero'], className)}>
      <span
        className={cn(
          styles['icon'],
          healthy ? styles['healthy'] : styles['unhealthy'],
        )}
        data-testid="health-icon"
      >
        {healthy ? <TickIcon /> : <WarningIcon />}
      </span>
      <div>
        <div className={styles['eyebrow']}>Status</div>
        <h2 className={styles['headline']}>{headline}</h2>
        <p className={styles['detail']}>{detail}</p>
      </div>
    </section>
  );
}
