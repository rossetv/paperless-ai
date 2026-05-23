import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SectionCard.module.css';

export interface SectionCardProps {
  /** The card heading — rendered as an `<h2>`. */
  title: string;
  /** Optional one-line description under the title. */
  subtitle?: string;
  /** Optional icon, shown in the accent-tinted header tile. */
  icon?: React.ReactNode;
  /** Optional badge shown beside the title — e.g. a connection StatusBadge. */
  badge?: React.ReactNode;
  /** DOM id — used as the in-page anchor target for the side-nav. */
  id?: string;
  /** The card body — typically a stack of `Row`s. */
  children: React.ReactNode;
  /** Additional class names to merge onto the card. */
  className?: string;
}

/**
 * A white rounded settings card with an iconised header and a body.
 *
 * Rendered as a `<section role="region">` labelled by its title, so each
 * settings section is an addressable landmark — assistive tech can jump
 * between sections and the side-nav anchors resolve to the `id`.
 *
 * Purely presentational — holds no domain knowledge. Tier:
 * components/primitives. Allowed deps: lib/, styles/.
 */
export function SectionCard({
  title,
  subtitle,
  icon,
  badge,
  id,
  children,
  className,
}: SectionCardProps): React.ReactElement {
  const headingId = id !== undefined ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      role="region"
      aria-labelledby={headingId}
      aria-label={headingId === undefined ? title : undefined}
      className={cn(styles['card'], className)}
    >
      <div className={styles['header']}>
        {icon !== undefined && <div className={styles['icon-tile']}>{icon}</div>}
        <div className={styles['header-text']}>
          <div className={styles['title-row']}>
            <h2 id={headingId} className={styles['title']}>
              {title}
            </h2>
            {badge}
          </div>
          {subtitle !== undefined && (
            <p className={styles['subtitle']}>{subtitle}</p>
          )}
        </div>
      </div>
      <div className={styles['body']}>{children}</div>
    </section>
  );
}
