import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../../../components/primitives/Icon/Icon';
import type { IndexHealthStatus } from '../../../api/types';
import styles from './IndexHealthHero.module.css';

/**
 * The icon styling and glyph for each health verdict.
 *
 * Three distinct tones: `ok` reads green with a tick, `degraded` reads amber
 * (a caution — the index is still serving, just not at full strength), and
 * `down` reads red (a genuine failure). `degraded` is deliberately *not* red:
 * conflating a missed heartbeat with a total outage overstates the problem.
 */
type HealthTone = 'ok' | 'caution' | 'down';

/** Human-readable label and tone for each health verdict. */
const HEALTH_PRESENTATION: Record<
  IndexHealthStatus,
  { headline: string; detail: string; tone: HealthTone; glyph: 'check' | 'warning' }
> = {
  ok: {
    headline: 'Healthy · ready to serve',
    detail: 'All daemons running and heartbeating within the stale window.',
    tone: 'ok',
    glyph: 'check',
  },
  degraded: {
    headline: 'Degraded · some daemons stopped',
    detail: 'One or more daemons have missed their heartbeat window.',
    tone: 'caution',
    glyph: 'warning',
  },
  down: {
    headline: 'Down · no daemons running',
    detail: 'All daemons have missed their heartbeat window or the index is unreadable.',
    tone: 'down',
    glyph: 'warning',
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
 * "Status" eyebrow + headline + detail. Three tones drive the icon tint:
 * green for `"ok"`, amber for `"degraded"` (caution, still serving) and red
 * for `"down"` (genuine failure).
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — takes a domain wire type.
 */
export function IndexHealthHero({
  health,
  className,
}: IndexHealthHeroProps): React.ReactElement {
  const { headline, detail, tone, glyph } = HEALTH_PRESENTATION[health];

  return (
    <section className={cn(styles['hero'], className)}>
      <span
        className={cn(styles['icon'], styles[tone])}
        data-testid="health-icon"
      >
        <Icon name={glyph} size="large" />
      </span>
      <div>
        <div className={styles['eyebrow']}>Status</div>
        <h2 className={styles['headline']}>{headline}</h2>
        <p className={styles['detail']}>{detail}</p>
      </div>
    </section>
  );
}
