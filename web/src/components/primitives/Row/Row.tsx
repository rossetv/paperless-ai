import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
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
  /**
   * When true, renders an amber "Rebuilds the index on save" pill beside the
   * label title to warn the user that saving will trigger a full index rebuild.
   */
  requiresReindex?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * One labelled setting inside a {@link SettingsCard}: a fixed-width label column
 * beside a flexible control column.
 */
export function Row({
  label,
  hint,
  env,
  controlId,
  last = false,
  isDefault = false,
  requiresReindex = false,
  children,
  className,
}: RowProps): React.ReactElement {
  return (
    <div className={cn(styles['row'], last && styles['row-last'], className)}>
      <div>
        <div className={styles['label-row']}>
          {controlId !== undefined ? (
            <label htmlFor={controlId} className={styles['label']}>
              {label}
            </label>
          ) : (
            <span className={styles['label']}>{label}</span>
          )}
          {requiresReindex && (
            <span className={styles['reindex-pill']}>
              <Icon name="arrows-rotate" size="small" />
              Rebuilds the index on save
            </span>
          )}
        </div>
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
