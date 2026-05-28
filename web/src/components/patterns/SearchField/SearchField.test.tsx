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
    // The search icon renders as a Font Awesome <i class="fa-solid fa-magnifying-glass">.
    expect(document.querySelector('i.fa-magnifying-glass')).toBeInTheDocument();
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

  it('renders pre-filled yet editable when given a defaultValue', async () => {
    const handleSubmit = vi.fn();
    render(
      <SearchField id="q" onSubmit={handleSubmit} defaultValue="old query" />,
    );
    const input = screen.getByRole('searchbox');
    expect(input).toHaveValue('old query');
    // The field is uncontrolled — the user can clear it and type a new query.
    await userEvent.clear(input);
    await userEvent.type(input, 'new query');
    await userEvent.keyboard('{Enter}');
    expect(handleSubmit).toHaveBeenCalledWith('new query');
  });

  it('disables the input and button when disabled prop is true', () => {
    render(<SearchField id="q" onSubmit={vi.fn()} disabled />);
    expect(screen.getByRole('searchbox')).toBeDisabled();
    expect(screen.getByRole('button', { name: /search/i })).toBeDisabled();
  });
});
