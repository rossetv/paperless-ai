/**
 * Lives in components/layout so the app tier (routes, main) can import it:
 * eslint-plugin-boundaries does not let the app tier import patterns.
 */

import React from 'react';
import styles from './ErrorBoundary.module.css';

interface Props {
  children: React.ReactNode;
  /** When any value changes (e.g. on route change), the boundary resets. */
  resetKeys?: unknown[];
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/** Catches render-time throws in its subtree and shows a fallback with a reload button. */
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

    // If any reset key has changed (including a length-only change), clear the error state.
    const prevKeys = prevProps.resetKeys ?? [];
    const changed =
      resetKeys.length !== prevKeys.length ||
      resetKeys.some((key, i) => key !== prevKeys[i]);
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
