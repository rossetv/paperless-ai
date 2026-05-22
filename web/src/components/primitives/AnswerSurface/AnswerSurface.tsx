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
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The synthesised-answer card shell.
 *
 * A bespoke surface: a "Synthesised answer" eyebrow with a spark glyph, the
 * answer prose (supplied as `children`, set in the display font), and a
 * provenance footer reporting the source count, the latency, and — when the
 * pipeline refined the answer — a "Refined once" marker.
 *
 * App-agnostic: it knows a source count and a latency, nothing about the
 * query. The `AnswerCard` feature supplies the prose.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function AnswerSurface({
  children,
  sourceCount,
  latencyMs,
  refined = false,
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
      </div>
    </article>
  );
}
