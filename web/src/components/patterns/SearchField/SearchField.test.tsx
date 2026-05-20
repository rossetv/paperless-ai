import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchField } from './SearchField';

describe('SearchField', () => {
  it('renders a search input', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('renders a search icon within the field', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} />);
    // The search icon SVG should be present (aria-hidden decorative)
    const svgs = document.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThan(0);
  });

  it('renders a submit button', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} />);
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument();
  });

  it('fires onSubmit with the current value when Enter is pressed', async () => {
    const handleSubmit = vi.fn();
    render(<SearchField id="q" onSubmit={handleSubmit} />);
    const input = screen.getByRole('searchbox');
    await userEvent.type(input, 'invoices');
    await userEvent.keyboard('{Enter}');
    expect(handleSubmit).toHaveBeenCalledWith('invoices');
  });

  it('fires onSubmit with the current value when the submit button is clicked', async () => {
    const handleSubmit = vi.fn();
    render(<SearchField id="q" onSubmit={handleSubmit} />);
    const input = screen.getByRole('searchbox');
    await userEvent.type(input, 'boiler warranty');
    await userEvent.click(screen.getByRole('button', { name: /search/i }));
    expect(handleSubmit).toHaveBeenCalledWith('boiler warranty');
  });

  it('does not fire onSubmit when Enter is pressed on an empty field', async () => {
    const handleSubmit = vi.fn();
    render(<SearchField id="q" onSubmit={handleSubmit} />);
    await userEvent.keyboard('{Enter}');
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  it('shows a placeholder when provided', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} placeholder="Search your documents…" />);
    expect(screen.getByPlaceholderText('Search your documents…')).toBeInTheDocument();
  });

  it('renders with a visible label when label prop is provided', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} label="Document search" />);
    // getByLabelText returns the input element the label points to
    expect(screen.getByLabelText('Document search')).toBeInTheDocument();
  });

  it('forwards a controlled value', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} value="prefilled" onChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toHaveValue('prefilled');
  });

  it('disables the input and button when disabled prop is true', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} disabled />);
    expect(screen.getByRole('searchbox')).toBeDisabled();
    expect(screen.getByRole('button', { name: /search/i })).toBeDisabled();
  });
});
