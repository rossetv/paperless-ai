import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Select } from './Select';

const OPTIONS = [
  { value: 'apple', label: 'Apple' },
  { value: 'banana', label: 'Banana' },
  { value: 'cherry', label: 'Cherry' },
];

describe('Select', () => {
  it('renders a combobox button with the placeholder when no value is selected', () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose a fruit"
      />,
    );
    expect(screen.getByRole('combobox', { name: /choose a fruit/i })).toBeInTheDocument();
  });

  it('shows the selected option label when value is provided', () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        value="banana"
        onChange={vi.fn()}
        placeholder="Choose a fruit"
      />,
    );
    expect(screen.getByRole('combobox')).toHaveTextContent('Banana');
  });

  it('opens the listbox when the combobox is clicked', async () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose a fruit"
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('shows all options when open', async () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose a fruit"
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    const optionEls = screen.getAllByRole('option');
    expect(optionEls).toHaveLength(3);
    expect(optionEls[0]).toHaveTextContent('Apple');
    expect(optionEls[2]).toHaveTextContent('Cherry');
  });

  it('calls onChange and closes the listbox when an option is clicked', async () => {
    const handleChange = vi.fn();
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={handleChange}
        placeholder="Choose"
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(screen.getByRole('option', { name: 'Cherry' }));
    expect(handleChange).toHaveBeenCalledWith('cherry');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('closes the listbox when Escape is pressed', async () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose"
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('moves highlight down with ArrowDown and selects with Enter', async () => {
    const handleChange = vi.fn();
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={handleChange}
        placeholder="Choose"
      />,
    );
    // Open with keyboard
    screen.getByRole('combobox').focus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    // First option is now highlighted — press Enter to select it
    await userEvent.keyboard('{Enter}');
    expect(handleChange).toHaveBeenCalledWith('apple');
  });

  it('moves highlight up with ArrowUp', async () => {
    const handleChange = vi.fn();
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={handleChange}
        placeholder="Choose"
      />,
    );
    screen.getByRole('combobox').focus();
    await userEvent.keyboard('{ArrowDown}');
    await userEvent.keyboard('{ArrowDown}');
    // Highlight is at index 1 (Banana); move up to Apple
    await userEvent.keyboard('{ArrowUp}');
    await userEvent.keyboard('{Enter}');
    expect(handleChange).toHaveBeenCalledWith('apple');
  });

  it('marks the selected option with aria-selected', async () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        value="banana"
        onChange={vi.fn()}
        placeholder="Choose"
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    const bananaOption = screen.getByRole('option', { name: 'Banana' });
    expect(bananaOption).toHaveAttribute('aria-selected', 'true');
  });

  it('is disabled when disabled prop is true', () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose"
        disabled
      />,
    );
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('shows a visible label when label prop is provided', () => {
    render(
      <Select
        id="fruit"
        label="Fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose"
      />,
    );
    expect(screen.getByText('Fruit')).toBeInTheDocument();
  });
});
