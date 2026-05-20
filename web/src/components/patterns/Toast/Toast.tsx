import React, { useEffect } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import { cn } from '../../../lib/cn';
import styles from './Toast.module.css';

/**
 * Variant values and their ARIA / token mappings.
 *
 * DESIGN.md uses a single chromatic accent (Apple Blue, --colour-accent) with
 * no semantic status colours. Two visually distinct treatments exist:
 *
 *   info  → --colour-accent border, role="status"  (informational, blue)
 *   error → --colour-text-primary border, role="alert" (near-black, assertive)
 *
 * The previous `success` variant was visually identical to `info` (both used
 * --colour-accent) — a misleading API. It is removed to keep the type honest.
 * Callers that previously used `success` should use `info`.
 */
export type ToastVariant = 'info' | 'error';

export interface ToastProps {
  /** The message to display inside the toast. */
  message: string;
  /** Visual and semantic variant. */
  variant: ToastVariant;
  /**
   * Called when the toast should be dismissed — either by the user clicking
   * the dismiss button or after `dismissAfterMs` elapses.
   * Required for auto-dismiss; optional for persistent toasts.
   */
  onDismiss?: () => void;
  /**
   * If provided, the toast fires `onDismiss` automatically after this many
   * milliseconds. Has no effect without `onDismiss`.
   */
  dismissAfterMs?: number;
  /** Additional class names to merge onto the root element. */
  className?: string;
}

// Icon per variant — decorative only; the toast's ARIA role carries the semantic
// meaning (role="status" for info, role="alert" for error). The icons are
// rendered inside an aria-hidden span, so they must not have a label — a
// labelled icon inside aria-hidden is self-contradictory markup.
const VARIANT_ICON: Record<ToastVariant, React.ReactElement> = {
  info: <Icon name="info" size="small" />,
  error: <Icon name="warning" size="small" />,
};

/**
 * Transient notification toast.
 *
 * Accessibility:
 * - role="status" for info/success — polite, does not interrupt the user.
 * - role="alert" for error — assertive, announced immediately.
 * - The dismiss button has an explicit aria-label.
 *
 * Auto-dismiss: when both `dismissAfterMs` and `onDismiss` are provided the
 * toast fires `onDismiss` after the timeout, clearing the timer on unmount.
 *
 * App-agnostic — carries no knowledge of documents, search, or facets.
 * Composes Icon and IconButton primitives.
 */
export function Toast({
  message,
  variant,
  onDismiss,
  dismissAfterMs,
  className,
}: ToastProps): React.ReactElement {
  // ── Auto-dismiss ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (dismissAfterMs === undefined || onDismiss === undefined) return undefined;

    const timer = window.setTimeout(onDismiss, dismissAfterMs);
    return () => window.clearTimeout(timer);
  }, [dismissAfterMs, onDismiss]);

  // ── ARIA role ─────────────────────────────────────────────────────────────
  // error is assertive (role="alert"); info is polite (role="status").
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
