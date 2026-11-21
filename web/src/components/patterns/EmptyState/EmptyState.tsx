import React from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './EmptyState.module.css';

export interface EmptyStateProps {
  /** Icon matching the empty scenario, e.g. "search" for no search results. */
  icon: IconName;
  /** Primary message explaining the empty state. */
  message: string;
  /** Optional secondary text below the message. */
  description?: string;
  /** Optional call to action, typically a `Button`, shown below the message. */
  action?: React.ReactNode;
  className?: string;
}

/**
 * Placeholder for an empty list or result set: an icon, a message, and an
 * optional description and call to action.
 */
export function EmptyState({
  icon,
  message,
  description,
  action,
  className,
}: EmptyStateProps): React.ReactElement {
  const rootClasses = cn(styles['empty-state'], className);

  return (
    <div className={rootClasses}>
      <span className={styles['icon-wrapper']} aria-hidden="true">
        <Icon name={icon} size="xlarge" />
      </span>

      <p className={styles['message']}>{message}</p>

      {description !== undefined && (
        <p className={styles['description']}>{description}</p>
      )}

      {action !== undefined && (
        <div className={styles['action']}>{action}</div>
      )}
    </div>
  );
}
