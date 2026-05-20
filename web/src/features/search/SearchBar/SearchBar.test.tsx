import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchBar } from './SearchBar';

describe('SearchBar', () => {
  it('renders a search input', () => {
    render(<SearchBar onSearch={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('calls onSearch with the query when the user submits', async () => {
    const handler = vi.fn();
    render(<SearchBar onSearch={handler} />);
    await userEvent.type(screen.getByRole('searchbox'), 'boiler warranty');
    await userEvent.keyboard('{Enter}');
    expect(handler).toHaveBeenCalledWith('boiler warranty');
  });

  it('calls onSearch when the submit button is clicked', async () => {
    const handler = vi.fn();
    render(<SearchBar onSearch={handler} />);
    await userEvent.type(screen.getByRole('searchbox'), 'invoice 2024');
    await userEvent.click(screen.getByRole('button', { name: /search/i }));
    expect(handler).toHaveBeenCalledWith('invoice 2024');
  });

  it('does not call onSearch when the query is empty', async () => {
    const handler = vi.fn();
    render(<SearchBar onSearch={handler} />);
    await userEvent.keyboard('{Enter}');
    expect(handler).not.toHaveBeenCalled();
  });

  it('reflects an initial query value when provided', () => {
    render(<SearchBar onSearch={vi.fn()} initialQuery="boiler" />);
    expect(screen.getByRole('searchbox')).toHaveValue('boiler');
  });

  it('disables the field when disabled=true', () => {
    render(<SearchBar onSearch={vi.fn()} disabled />);
    expect(screen.getByRole('searchbox')).toBeDisabled();
  });
});
