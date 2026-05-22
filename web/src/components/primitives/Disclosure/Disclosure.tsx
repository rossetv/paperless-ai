import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './Disclosure.module.css';

export interface DisclosureProps {
  /** The always-visible summary row content (left of the stat read-out). */
  summary: React.ReactNode;
  /** The collapsible body content, revealed when the panel is open. */
  children: React.ReactNode;
  /** Whether the panel starts open. Defaults to false (collapsed). */
  defaultOpen?: boolean;
  /** Additional class names to merge onto the <details> element. */
  className?: string;
}

/**
 * A collapsible disclosure panel built on native `<details>`/`<summary>`.
 *
 * The summary row carries a chevron that rotates a quarter-turn when open
 * (respecting `prefers-reduced-motion`). Using the native element means
 * keyboard operation and the open/closed state come for free.
 *
 * App-agnostic — knows nothing about query plans. `QueryPlanSummary`
 * composes it.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  className,
}: DisclosureProps): React.ReactElement {
  return (
    <details
      className={cn(styles['disclosure'], className)}
      {...(defaultOpen ? { open: true } : {})}
    >
      <summary className={styles['summary']}>
        <span className={styles['chevron']} aria-hidden="true">
          <Icon name="chevron-right" size="small" />
        </span>
        {summary}
      </summary>
      <div className={styles['body']}>{children}</div>
    </details>
  );
}
