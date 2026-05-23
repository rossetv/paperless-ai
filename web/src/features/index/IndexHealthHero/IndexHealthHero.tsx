import { cn } from '../../../lib/cn';
import type { IndexHealth } from '../../../api/types';
import styles from './IndexHealthHero.module.css';

/**
 * Format an ISO-8601 timestamp as a UK long date — "7 May 2026".
 *
 * Returns `null` for a `null` input so the caller can omit the line. Uses
 * `en-GB` locale formatting (day · month name · year).
 */
function formatSince(iso: string | null): string | null {
  if (iso === null) {
    return null;
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

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
  /** The overall index health, from GET /api/index/status. */
  health: IndexHealth;
  /** Additional class names to merge onto the root. */
  className?: string;
}

/**
 * The Index dashboard health hero.
 *
 * A circular status icon (tick when healthy, warning triangle otherwise), a
 * "Status" eyebrow + headline + detail, and a right-aligned uptime block.
 * The icon tint and glyph flip on `health.healthy`.
 *
 * Tier: features/index (CODE_GUIDELINES §12.3) — takes a domain wire type.
 */
export function IndexHealthHero({
  health,
  className,
}: IndexHealthHeroProps): React.ReactElement {
  const since = formatSince(health.since);

  return (
    <section className={cn(styles['hero'], className)}>
      <span
        className={cn(
          styles['icon'],
          health.healthy ? styles['healthy'] : styles['unhealthy'],
        )}
        data-testid="health-icon"
      >
        {health.healthy ? <TickIcon /> : <WarningIcon />}
      </span>
      <div>
        <div className={styles['eyebrow']}>Status</div>
        <h2 className={styles['headline']}>{health.headline}</h2>
        <p className={styles['detail']}>{health.detail}</p>
      </div>
      <div className={styles['uptime']}>
        <span className={styles['eyebrow']}>Uptime</span>
        <span className={styles['uptime-value']}>{health.uptime}</span>
        {since !== null && (
          <span className={styles['uptime-since']}>since {since}</span>
        )}
      </div>
    </section>
  );
}
