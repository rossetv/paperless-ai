import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SettingsCard.module.css';

export interface SettingsCardProps {
  /** The sub-card heading — rendered as an `<h3>`. */
  title: string;
  /** Optional one-line description shown under the title. */
  subtitle?: string;
  /** Optional slot for actions in the card header (e.g. a test-connection button). */
  headerActions?: React.ReactNode;
  /** The card body — typically a stack of `Row`s. */
  children: React.ReactNode;
  className?: string;
}

/**
 * A sub-card within a settings section: a header (title, optional subtitle and
 * actions) above a body of `Row`s.
 */
export function SettingsCard({
  title,
  subtitle,
  headerActions,
  children,
  className,
}: SettingsCardProps): React.ReactElement {
  return (
    <div className={cn(styles['card'], className)}>
      <div className={styles['header']}>
        <div className={styles['header-info']}>
          <h3 className={styles['title']}>{title}</h3>
          {subtitle !== undefined && (
            <p className={styles['subtitle']}>{subtitle}</p>
          )}
        </div>
        {headerActions !== undefined && (
          <div className={styles['header-actions']}>{headerActions}</div>
        )}
      </div>
      <div className={styles['body']}>{children}</div>
    </div>
  );
}
