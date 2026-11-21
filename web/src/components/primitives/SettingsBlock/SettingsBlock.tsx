import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SettingsBlock.module.css';

export interface SettingsBlockProps {
  /** The section heading — rendered as an `<h2>`. */
  title: string;
  /** Optional right-aligned caption under the title. */
  subtitle?: string;
  /** DOM id — used as the in-page anchor target for the side-nav. */
  id?: string;
  /** The block body — a stack of `SettingsCard`s. */
  children: React.ReactNode;
  className?: string;
}

/**
 * A settings section: a large `<h2>` with a right-aligned subtitle and a bottom
 * hairline, followed by a stack of `SettingsCard`s.
 */
export function SettingsBlock({
  title,
  subtitle,
  id,
  children,
  className,
}: SettingsBlockProps): React.ReactElement {
  const headingId = id !== undefined ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      role="region"
      aria-labelledby={headingId}
      aria-label={headingId === undefined ? title : undefined}
      className={cn(styles['block'], className)}
    >
      <div className={styles['header']}>
        <h2 id={headingId} className={styles['title']}>
          {title}
        </h2>
        {subtitle !== undefined && (
          <p className={styles['subtitle']}>{subtitle}</p>
        )}
      </div>
      <div className={styles['body']}>{children}</div>
    </section>
  );
}
