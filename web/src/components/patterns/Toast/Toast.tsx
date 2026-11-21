import React, { useEffect } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { cn } from '../../../lib/cn';
import styles from './Toast.module.css';

/** 'info' is polite (role="status"); 'error' is assertive (role="alert"). */
export type ToastVariant = 'info' | 'error';

export interface ToastProps {
  message: string;
  variant: ToastVariant;
  /** Called on a dismiss-button click, or after `dismissAfterMs` when that is set. */
  onDismiss?: () => void;
  /**
   * If provided, the toast fires `onDismiss` automatically after this many
   * milliseconds. Has no effect without `onDismiss`.
   */
  dismissAfterMs?: number;
  className?: string;
}

// Decorative: the toast's role carries the meaning, and the icons sit inside an
// aria-hidden span, so they must not have a label.
const VARIANT_ICON: Record<ToastVariant, React.ReactElement> = {
  info: <Icon name="info" size="small" />,
  error: <Icon name="warning" size="small" />,
};

/**
 * Transient notification toast. Auto-dismisses after `dismissAfterMs` when both
 * that and `onDismiss` are provided.
 */
export function Toast({
  message,
  variant,
  onDismiss,
  dismissAfterMs,
  className,
}: ToastProps): React.ReactElement {
  useEffect(() => {
    if (dismissAfterMs === undefined || onDismiss === undefined) return undefined;

    const timer = window.setTimeout(onDismiss, dismissAfterMs);
    return () => window.clearTimeout(timer);
  }, [dismissAfterMs, onDismiss]);

  const role = variant === 'error' ? 'alert' : 'status';

  const rootClasses = cn(
    styles['toast'],
    styles[variant],
    className,
  );

  return (
    <div role={role} className={rootClasses}>
      <span className={styles['icon']} aria-hidden="true">
        {VARIANT_ICON[variant]}
      </span>

      <span className={styles['message']}>{message}</span>

      {onDismiss !== undefined && (
        <IconButton
          label="Dismiss notification"
          onClick={onDismiss}
          {...(styles['dismiss-button'] !== undefined
            ? { className: styles['dismiss-button'] }
            : {})}
        >
          <Icon name="close" size="small" />
        </IconButton>
      )}
    </div>
  );
}
