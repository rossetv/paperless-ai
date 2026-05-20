import React, { useEffect } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { IconButton } from '../../primitives/IconButton/IconButton';
import stylesRaw from './Toast.module.css';

// CSS Modules return a string-indexed object; bracket notation is required
// under noPropertyAccessFromIndexSignature (tsconfig strict mode).
const styles = stylesRaw as Record<string, string>;

/**
 * Variant values and their ARIA / token mappings.
 *
 * DESIGN.md uses a single chromatic accent (Apple Blue, --colour-accent) with
 * no semantic error/success colours. We therefore map variants as follows —
 * documented here because it is a deliberate design decision, not an oversight:
 *
 *   info    → --colour-accent border, role="status"    (informational, blue)
 *   success → --colour-accent border, role="status"    (same blue — only available accent)
 *   error   → --colour-text-primary border, role="alert"  (near-black, higher urgency)
 *
 * The visual differentiation relies on the icon and the stronger ARIA role
 * rather than a separate colour, which is consistent with the Apple palette
 * constraint.
 */
export type ToastVariant = 'info' | 'success' | 'error';

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

// Icon per variant — maps to the Icon primitive's closed icon name set.
const VARIANT_ICON: Record<ToastVariant, React.ReactElement> = {
  info: <Icon name="info" size="small" label="Info" />,
  success: <Icon name="check" size="small" label="Success" />,
  error: <Icon name="warning" size="small" label="Error" />,
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
  // error is assertive (role="alert"); info/success are polite (role="status").
  const role = variant === 'error' ? 'alert' : 'status';

  const rootClasses = [
    styles['toast'],
    styles[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');

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
