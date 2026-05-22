import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchErrorScreen } from './SearchErrorScreen';

function renderScreen(overrides = {}) {
  return render(
    <SearchErrorScreen
      query="how much did I pay npower in 2024"
      message="API error 500"
      onRetry={() => {}}
      onSearch={() => {}}
      {...overrides}
    />,
  );
}

describe('SearchErrorScreen', () => {
  it('states that the search failed', () => {
    renderScreen();
    expect(screen.getByText(/search failed/i)).toBeInTheDocument();
  });

  it('shows the error detail message', () => {
    renderScreen();
    expect(screen.getByText(/API error 500/)).toBeInTheDocument();
  });

  it('renders a "Try again" action', () => {
    renderScreen();
    expect(
      screen.getByRole('button', { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it('fires onRetry when "Try again" is clicked', async () => {
    const onRetry = vi.fn();
    renderScreen({ onRetry });
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('recaps the failed query in an editable field', () => {
    renderScreen();
    expect(
      screen.getByDisplayValue('how much did I pay npower in 2024'),
    ).toBeInTheDocument();
  });

  it('runs a fresh search when the recap field is submitted', async () => {
    // The user must not be stranded on the error: editing and submitting
    // the recap field starts a new search.
    const onSearch = vi.fn();
    renderScreen({ onSearch });
    const recap = screen.getByDisplayValue(
      'how much did I pay npower in 2024',
    );
    await userEvent.clear(recap);
    await userEvent.type(recap, 'gas bill 2023{Enter}');
    expect(onSearch).toHaveBeenCalledWith('gas bill 2023');
  });
});
