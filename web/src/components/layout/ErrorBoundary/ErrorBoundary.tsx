/**
 * ErrorBoundary — catches render-time throws and shows a friendly fallback.
 *
 * React only exposes error boundary semantics as a class component (no hook
 * equivalent). This is a thin, reusable wrapper that follows the project's
 * component conventions:
 *
 *   - Friendly fallback with a reload affordance so the user is never stuck
 *     on a blank screen.
 *   - `resetKeys` prop: when any value in the array changes the boundary
 *     automatically resets (e.g. on route change), giving a clean slate
 *     without requiring a full page reload.
 *   - The fallback is styled with design-token CSS custom properties; no
 *     hardcoded colours.
 *
 * Placement:
 *   - App root (`main.tsx`) — catches any catastrophic render failure.
 *   - Lazy-route wrapper in `routes.tsx` — isolates per-page crashes.
 *   - Trace / free-form JSON views — isolates widget-level crashes.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3) — placed here so the `app`
 * tier (routes, main) can import it; `components-patterns` is not in the
 * app allow-list (eslint-plugin-boundaries).
 */

import React from 'react';
import styles from './ErrorBoundary.module.css';

interface Props {
  children: React.ReactNode;
  /**
   * When any value in this array changes, the boundary resets automatically.
   * Useful for resetting after a route change without requiring a page reload.
   */
  resetKeys?: unknown[];
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Class component error boundary.
 *
 * Catches render-time exceptions in the subtree and renders a recovery
 * fallback in place of the crashed UI. A "Reload page" button lets the user
 * escape without manually refreshing.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log to console so engineers can see the trace in DevTools without
    // needing a monitoring service wired up.
    console.error('[ErrorBoundary] caught render error:', error, info.componentStack);
  }

  componentDidUpdate(prevProps: Props): void {
    const { resetKeys } = this.props;
    const { hasError } = this.state;

    if (!hasError || resetKeys === undefined) {
      return;
    }

    // If any reset key has changed, clear the error state.
    const prevKeys = prevProps.resetKeys ?? [];
    const changed = resetKeys.some((key, i) => key !== prevKeys[i]);
    if (changed) {
      this.setState({ hasError: false, error: null });
    }
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className={styles['boundary']} role="alert" aria-live="assertive">
          <p className={styles['message']}>Something went wrong — reload?</p>
          <button
            className={styles['reload']}
            type="button"
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
