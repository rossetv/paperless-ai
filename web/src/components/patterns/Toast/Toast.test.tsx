import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { Toast } from './Toast';

describe('Toast', () => {
  it('renders the message text', () => {
    render(<Toast message="Document indexed successfully" variant="info" />);
    expect(screen.getByText('Document indexed successfully')).toBeInTheDocument();
  });

  it('uses role="status" for info variant', () => {
    render(<Toast message="Indexing in progress" variant="info" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('uses role="alert" for error variant', () => {
    render(<Toast message="Something went wrong" variant="error" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('renders the dismiss button when onDismiss is provided', () => {
    render(<Toast message="Hello" variant="info" onDismiss={vi.fn()} />);
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument();
  });

  it('does not render a dismiss button when onDismiss is not provided', () => {
    render(<Toast message="Hello" variant="info" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('calls onDismiss when the dismiss button is clicked', async () => {
    const handleDismiss = vi.fn();
    render(<Toast message="Notification" variant="info" onDismiss={handleDismiss} />);
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(handleDismiss).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss after the auto-dismiss timeout', () => {
    vi.useFakeTimers();
    const handleDismiss = vi.fn();
    render(
      <Toast
        message="Auto dismissing"
        variant="info"
        dismissAfterMs={3000}
        onDismiss={handleDismiss}
      />,
    );
    expect(handleDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3000);
    expect(handleDismiss).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('does not call onDismiss before the auto-dismiss timeout elapses', () => {
    vi.useFakeTimers();
    const handleDismiss = vi.fn();
    render(
      <Toast
        message="Auto dismissing"
        variant="info"
        dismissAfterMs={3000}
        onDismiss={handleDismiss}
      />,
    );
    vi.advanceTimersByTime(2999);
    expect(handleDismiss).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
