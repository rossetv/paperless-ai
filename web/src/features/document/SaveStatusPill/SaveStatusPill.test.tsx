import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SaveStatusPill } from './SaveStatusPill';

describe('SaveStatusPill', () => {
  it('renders "Saved" label and role="status" for idle state', () => {
    render(<SaveStatusPill status="idle" />);
    expect(screen.getByRole('status')).toHaveTextContent('Saved');
  });

  it('renders "Saving…" label and role="status" for saving state', () => {
    render(<SaveStatusPill status="saving" />);
    expect(screen.getByRole('status')).toHaveTextContent('Saving…');
  });

  it('renders "Saved" label and role="status" for saved state', () => {
    render(<SaveStatusPill status="saved" />);
    expect(screen.getByRole('status')).toHaveTextContent('Saved');
  });

  it('renders "View only" label and role="status" for readonly state', () => {
    render(<SaveStatusPill status="readonly" />);
    expect(screen.getByRole('status')).toHaveTextContent('View only');
  });

  it('renders error state as a button with role="alert" when onRetry is provided', () => {
    render(<SaveStatusPill status="error" onRetry={vi.fn()} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('calls onRetry when the error button is clicked', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<SaveStatusPill status="error" onRetry={onRetry} />);
    await user.click(screen.getByRole('alert'));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders error state as a non-interactive span when onRetry is absent', () => {
    render(<SaveStatusPill status="error" />);
    // Without onRetry the error state falls through to the span branch.
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
