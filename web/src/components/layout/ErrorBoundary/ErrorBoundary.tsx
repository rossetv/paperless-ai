/**
 * Lives in components/layout so the app tier (routes, main) can import it:
 * eslint-plugin-boundaries does not let the app tier import patterns.
 */

import React from 'react';
import { Button } from '../../primitives/Button/Button';
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

/** Catches render-time throws in its subtree and shows a full-screen fallback with a heading and a reload button. */
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
        <main className={styles['boundary']}>
          <div role="alert" aria-live="assertive">
            <h1 className={styles['heading']}>Something went wrong</h1>
          </div>
          <Button onClick={() => window.location.reload()}>Reload page</Button>
        </main>
      );
    }

    return this.props.children;
  }
}
