import React from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './EmptyState.module.css';

export interface EmptyStateProps {
  /**
   * Icon to display — uses the Icon primitive's closed name union for
   * compile-time safety. Choose an icon that contextually matches the
   * empty scenario (e.g. "search" for no search results, "document" for
   * an empty document list).
   */
  icon: IconName;
  /** Primary message explaining the empty state. */
  message: string;
  /**
   * Optional secondary text providing context or guidance, rendered below
   * the primary message.
   */
  description?: string;
  /**
   * Optional call-to-action. Pass a rendered element — typically a `Button`
   * primitive — and it will be displayed below the message.
   * When omitted, no action area is rendered.
   */
  action?: React.ReactNode;
  /** Additional class names to merge onto the root element. */
  className?: string;
}

/**
 * Empty / placeholder state display.
 *
 * Renders an icon, a primary message, an optional description, and an optional
 * call-to-action. Designed to fill the space left by an absent list or result
 * set, guiding the user toward a productive next step.
 *
 * App-agnostic — carries no knowledge of documents, search, or facets.
 * Composes the Icon primitive; the action is passed as an opaque ReactNode
 * so callers can provide any appropriate control (Button, Link, etc.).
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
