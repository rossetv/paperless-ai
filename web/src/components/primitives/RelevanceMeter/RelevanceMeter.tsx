import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './RelevanceMeter.module.css';

/**
 * Qualitative relevance tier. Mirrors `RelevanceTier` in `api/types/search.ts`
 * — kept local so this primitive has no upward dependency on the api layer
 * (CODE_GUIDELINES §12.3). Must be kept in sync with the api type.
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
  /** Additional class names merged onto the root element. */
  className?: string;
}

/**
 * The relevance badge: a four-dot meter (filled dots = match strength) plus a
 * label — "Strong / Good / Partial / Weak match".
 *
 * Replaces the raw RRF "relevance · 0.05" number, which read as a misleadingly
 * tiny score even for a perfect hit. The dots give an at-a-glance scale; the
 * label spells the tier out.
 *
 * DESIGN.md: monochrome only — filled dots use `--colour-text-primary`, empty
 * dots the faint `--colour-border`; no status colour (the blue accent is
 * reserved for interactive elements). Mirrors the PipelineStages status dots.
 * The dots are decorative (`aria-hidden`); the visible label carries the
 * meaning for assistive tech.
 *
 * Tier: components/primitives — presentational, no data fetching.
 */
export function RelevanceMeter({
  tier,
  className,
}: RelevanceMeterProps): React.ReactElement {
  const { filled, label } = TIER_META[tier];
  return (
    <span className={cn(styles['meter'], className)}>
      <span className={styles['dots']} aria-hidden="true">
        {Array.from({ length: DOT_COUNT }, (_, i) => (
          <span
            key={i}
            data-filled={i < filled}
            className={cn(styles['dot'], i < filled ? styles['filled'] : styles['empty'])}
          />
        ))}
      </span>
      <span className={styles['label']}>{label}</span>
    </span>
  );
}
