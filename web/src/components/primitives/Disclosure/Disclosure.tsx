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
  className?: string;
}

/**
 * Collapsible panel on native `<details>`/`<summary>`, so keyboard operation and
 * the open state come for free.
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
