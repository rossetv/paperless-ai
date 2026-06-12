/**
 * Tests for the ErrorBoundary component.
 *
 * Strategy: render a child component that throws on cue; assert that
 * the fallback UI is shown and the throwing child is not rendered.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary';

// Suppress the expected console.error output from the caught throw so the
// test output stays clean.
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// A component that throws unconditionally.
function Bomb(): React.ReactElement {
  throw new Error('test bomb');
}

// A component that throws only when `shouldThrow` is true.
function ConditionalBomb({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) {
    throw new Error('conditional bomb');
  }
  return <span>safe</span>;
}

describe('ErrorBoundary', () => {
  it('renders children normally when no error is thrown', () => {
    render(
      <ErrorBoundary>
        <span>all good</span>
      </ErrorBoundary>,
    );
    expect(screen.getByText('all good')).toBeInTheDocument();
  });

  it('renders the fallback message when a child throws', () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });

  it('does not render the throwing child when a child throws', () => {
    // The child never renders its own content — only the fallback is visible.
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    // The Bomb renders nothing before throwing, so this verifies the
    // boundary fallback has replaced the subtree.
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('all good')).not.toBeInTheDocument();
  });

  it('renders a Reload page button in the fallback', () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('button', { name: /reload page/i })).toBeInTheDocument();
  });

  it('calls window.location.reload when the reload button is clicked', () => {
    const reloadSpy = vi.fn();
    // jsdom does not implement location.reload; stub it.
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload: reloadSpy },
      writable: true,
    });

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByRole('button', { name: /reload page/i }));
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('resets when a resetKey changes', () => {
    const { rerender } = render(
      <ErrorBoundary resetKeys={['route-a']}>
        <Bomb />
      </ErrorBoundary>,
    );

    // Boundary is in error state.
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();

    // Changing the reset key clears the error — the safe child renders.
    rerender(
      <ErrorBoundary resetKeys={['route-b']}>
        <ConditionalBomb shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
    expect(screen.getByText('safe')).toBeInTheDocument();
  });
});
