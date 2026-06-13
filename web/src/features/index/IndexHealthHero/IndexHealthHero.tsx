import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../../../components/primitives/Icon/Icon';
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
        <Icon name={healthy ? 'check' : 'warning'} size="large" />
      </span>
      <div>
        <div className={styles['eyebrow']}>Status</div>
        <h2 className={styles['headline']}>{headline}</h2>
        <p className={styles['detail']}>{detail}</p>
      </div>
    </section>
  );
}
