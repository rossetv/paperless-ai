import React, { useEffect, useRef, useState } from 'react';
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
 * Transient notification toast, fixed at the bottom centre above the save bar
 * and the mobile tab bar. Auto-dismisses after `dismissAfterMs` when both that
 * and `onDismiss` are provided; the countdown pauses while hovered or focused.
 */
export function Toast({
  message,
  variant,
  onDismiss,
  dismissAfterMs,
  className,
}: ToastProps): React.ReactElement {
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  const canAutoDismiss = dismissAfterMs !== undefined && onDismiss !== undefined;

  const remainingRef = useRef(dismissAfterMs ?? 0);
  useEffect(() => {
    remainingRef.current = dismissAfterMs ?? 0;
  }, [dismissAfterMs]);

  // Runs while not paused; on pause or unmount the elapsed time is taken off
  // what is left, so a resume carries on instead of starting over.
  useEffect(() => {
    if (!canAutoDismiss || paused) return undefined;

    const startedAt = Date.now();
    const timer = window.setTimeout(() => onDismissRef.current?.(), remainingRef.current);
    return () => {
      window.clearTimeout(timer);
      remainingRef.current = Math.max(0, remainingRef.current - (Date.now() - startedAt));
    };
  }, [canAutoDismiss, paused, dismissAfterMs]);

  const role = variant === 'error' ? 'alert' : 'status';

  const rootClasses = cn(
    styles['toast'],
    styles[variant],
    className,
  );

  return (
    <div
      role={role}
      className={rootClasses}
      onPointerEnter={(event) => {
        if (event.pointerType === 'mouse') setHovered(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === 'mouse') setHovered(false);
      }}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
    >
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
