import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Row.module.css';

export interface RowProps {
  /** The setting's label, shown in the left column. */
  label: string;
  /** Optional explanatory text under the label. */
  hint?: React.ReactNode;
  /** Optional config-key name, shown as a small monospace tag. */
  env?: string;
  /**
   * The id of the control in the right column. When given, the label is a
   * real `<label htmlFor>` — clicking it focuses the control. Omit it for a
   * row whose control is not a single labellable element (a Segmented group,
   * a button cluster), in which case the label renders as a plain span.
   */
  controlId?: string;
  /** Drop the bottom divider — set on the final row of a card. */
  last?: boolean;
  /**
   * When true, renders a subtle "default" badge in the control column to
   * signal that this key is on its coded default, not an explicit override.
   */
  isDefault?: boolean;
  /** The control element(s) for the right column. */
  children: React.ReactNode;
  /** Additional class names to merge onto the row. */
  className?: string;
}

/**
 * One labelled setting inside a {@link SectionCard}.
 *
 * A two-column grid: a fixed-width label column (label, optional hint,
 * optional `env` config-key tag) and a flexible control column. The label is
 * a `<label htmlFor>` when `controlId` is supplied — so the hit target
 * includes the text — and a plain `<span>` otherwise.
 *
 * Purely presentational. Tier: components/primitives. Allowed deps: lib/,
 * styles/.
 */
export function Row({
  label,
  hint,
  env,
  controlId,
  last = false,
  isDefault = false,
  children,
  className,
}: RowProps): React.ReactElement {
  return (
    <div className={cn(styles['row'], last && styles['row-last'], className)}>
      <div>
        {controlId !== undefined ? (
          <label htmlFor={controlId} className={styles['label']}>
            {label}
          </label>
        ) : (
          <span className={styles['label']}>{label}</span>
        )}
        {hint !== undefined && <p className={styles['hint']}>{hint}</p>}
        {env !== undefined && <span className={styles['env']}>{env}</span>}
      </div>
      <div className={styles['control']}>
        {children}
        {isDefault && <span className={styles['default-badge']}>default</span>}
      </div>
    </div>
  );
}
