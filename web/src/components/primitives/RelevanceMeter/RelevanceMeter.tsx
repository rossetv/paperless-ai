import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './RelevanceMeter.module.css';

/**
 * Mirrors `RelevanceTier` in `api/types/search.ts`; kept local so this primitive
 * does not depend on the api layer. Keep the two in sync.
 */
export type RelevanceTier = 'strong' | 'good' | 'partial' | 'weak';

/** How many of the four dots a tier fills, and the label it shows. */
const TIER_META: Record<RelevanceTier, { filled: number; label: string }> = {
  strong: { filled: 4, label: 'Strong match' },
  good: { filled: 3, label: 'Good match' },
  partial: { filled: 2, label: 'Partial match' },
  weak: { filled: 1, label: 'Weak match' },
};

const DOT_COUNT = 4;

export interface RelevanceMeterProps {
  /** The qualitative relevance tier from the search backend. */
  tier: RelevanceTier;
  className?: string;
}

/**
 * Relevance badge: a four-dot meter plus a "Strong / Good / Partial / Weak match"
 * label. The dots are aria-hidden; the label and the root's aria-label carry the
 * meaning.
 */
export function RelevanceMeter({
  tier,
  className,
}: RelevanceMeterProps): React.ReactElement {
  const { filled, label } = TIER_META[tier];
  return (
    <span
      className={cn(styles['meter'], className)}
      title={label}
      aria-label={label}
    >
      <span className={styles['dots']} aria-hidden="true">
        {Array.from({ length: DOT_COUNT }, (_, i) => {
          const isFilled = i < filled;
          return (
            <span
              key={i}
              data-filled={isFilled}
              className={cn(styles['dot'], isFilled ? styles['filled'] : styles['empty'])}
            />
          );
        })}
      </span>
      <span className={styles['label']}>{label}</span>
    </span>
  );
}
