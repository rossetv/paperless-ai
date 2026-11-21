import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './AnswerSurface.module.css';

export interface AnswerSurfaceProps {
  /** The synthesised-answer prose (text and inline citation marks). */
  children: React.ReactNode;
  /** Number of sources the answer was synthesised from. */
  sourceCount: number;
  /** Pipeline latency in milliseconds — shown as seconds in the footer. */
  latencyMs: number;
  /** Whether the pipeline ran a refinement pass. Defaults to false. */
  refined?: boolean;
  /**
   * Compact token label for the whole query (e.g. "29k tok"), shown as a footer
   * chip. Omitted when undefined, e.g. on a cache hit with no spend.
   */
  costLabel?: string;
  className?: string;
}

/**
 * Synthesised-answer card: a spark eyebrow, the answer prose (`children`) and a
 * provenance footer with the source count, latency and an optional "Refined once" marker.
 */
export function AnswerSurface({
  children,
  sourceCount,
  latencyMs,
  refined = false,
  costLabel,
  className,
}: AnswerSurfaceProps): React.ReactElement {
  const latencySeconds = (latencyMs / 1000).toFixed(1);

  return (
    <article className={cn(styles['surface'], className)}>
      <div className={styles['eyebrow']}>
        <span className={styles['spark']} aria-hidden="true">
          <Icon name="info" size="small" />
        </span>
        <span className={styles['eyebrow-label']}>Synthesised answer</span>
      </div>

      <p className={styles['prose']}>{children}</p>

      <div className={styles['footer']}>
        <span>
          Synthesised from {sourceCount}{' '}
          {sourceCount === 1 ? 'source' : 'sources'}
        </span>
        <span>{latencySeconds}s</span>
        {refined && (
          <span className={styles['refined']}>
            <span className={styles['refined-dot']} aria-hidden="true" />
            Refined once
          </span>
        )}
        {costLabel !== undefined && (
          <span className={styles['cost']}>{costLabel}</span>
        )}
      </div>
    </article>
  );
}
