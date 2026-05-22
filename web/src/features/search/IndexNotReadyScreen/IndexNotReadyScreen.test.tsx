import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IndexNotReadyScreen } from './IndexNotReadyScreen';

describe('IndexNotReadyScreen', () => {
  it('states that the index is initialising', () => {
    render(<IndexNotReadyScreen onRetry={() => {}} />);
    expect(screen.getByText(/the index is initialising/i)).toBeInTheDocument();
  });

  it('explains what is happening', () => {
    render(<IndexNotReadyScreen onRetry={() => {}} />);
    expect(
      screen.getByText(/embedding your library/i),
    ).toBeInTheDocument();
  });

  it('renders a "Retry now" action', () => {
    render(<IndexNotReadyScreen onRetry={() => {}} />);
    expect(
      screen.getByRole('button', { name: /retry now/i }),
    ).toBeInTheDocument();
  });

  it('fires onRetry when "Retry now" is clicked', async () => {
    const onRetry = vi.fn();
    render(<IndexNotReadyScreen onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: /retry now/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
