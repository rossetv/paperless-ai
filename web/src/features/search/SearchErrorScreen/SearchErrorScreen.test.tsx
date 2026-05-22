import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchErrorScreen } from './SearchErrorScreen';

describe('SearchErrorScreen', () => {
  it('states that the search failed', () => {
    render(<SearchErrorScreen message="API error 500" onRetry={() => {}} />);
    expect(screen.getByText(/search failed/i)).toBeInTheDocument();
  });

  it('shows the error detail message', () => {
    render(<SearchErrorScreen message="API error 500" onRetry={() => {}} />);
    expect(screen.getByText(/API error 500/)).toBeInTheDocument();
  });

  it('renders a "Try again" action', () => {
    render(<SearchErrorScreen message="x" onRetry={() => {}} />);
    expect(
      screen.getByRole('button', { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it('fires onRetry when "Try again" is clicked', async () => {
    const onRetry = vi.fn();
    render(<SearchErrorScreen message="x" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
