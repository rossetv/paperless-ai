import { createEvent, fireEvent, render, screen } from '@testing-library/react';
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

  it('closes on an outside pointer-down', async () => {
    render(
      <div>
        <Select
          id="fruit"
          options={OPTIONS}
          onChange={vi.fn()}
          placeholder="Choose a fruit"
        />
        <button type="button">outside</button>
      </div>,
    );
    await userEvent.click(screen.getByRole('combobox'));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('closes the first dropdown when a second is opened', async () => {
    render(
      <div>
        <Select id="fruit" options={OPTIONS} onChange={vi.fn()} placeholder="Fruit" />
        <Select
          id="colour"
          options={[
            { value: 'red', label: 'Red' },
            { value: 'blue', label: 'Blue' },
          ]}
          onChange={vi.fn()}
          placeholder="Colour"
        />
      </div>,
    );
    const [fruitTrigger, colourTrigger] = screen.getAllByRole('combobox');
    // Open the first dropdown.
    await userEvent.click(fruitTrigger!);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    // Opening the second dropdown is an outside-click for the first.
    await userEvent.click(colourTrigger!);
    // Only one listbox should be visible — the second one (colour).
    const listboxes = screen.getAllByRole('listbox');
    expect(listboxes).toHaveLength(1);
    expect(listboxes[0]).toHaveAttribute('id', 'colour-listbox');
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

  it('sets aria-activedescendant to the highlighted option id as arrow keys move the highlight', async () => {
    render(
      <Select
        id="fruit"
        options={OPTIONS}
        onChange={vi.fn()}
        placeholder="Choose"
      />,
    );
    const combobox = screen.getByRole('combobox');
    combobox.focus();

    // Open and highlight the first item
    await userEvent.keyboard('{ArrowDown}');
    expect(combobox).toHaveAttribute('aria-activedescendant', 'fruit-option-0');

    // Move to second item
    await userEvent.keyboard('{ArrowDown}');
    expect(combobox).toHaveAttribute('aria-activedescendant', 'fruit-option-1');

    // Move back to first
    await userEvent.keyboard('{ArrowUp}');
    expect(combobox).toHaveAttribute('aria-activedescendant', 'fruit-option-0');
  });
});

describe('Select keyboard and semantics', () => {
  function setup(extra: { onChange?: (v: string) => void } = {}) {
    const onChange = extra.onChange ?? vi.fn();
    render(
      <>
        <Select id="fruit" options={OPTIONS} onChange={onChange} placeholder="Pick" />
        <button type="button">after</button>
      </>,
    );
    return { onChange, trigger: screen.getByRole('combobox') };
  }

  it('Escape on an open list closes it, is default-prevented and does not reach the document', () => {
    const { trigger } = setup();
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    fireEvent.click(trigger);
    const escape = createEvent.keyDown(trigger, { key: 'Escape' });
    fireEvent(trigger, escape);
    document.removeEventListener('keydown', seen);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(escape.defaultPrevented).toBe(true);
    expect(seen).not.toHaveBeenCalled();
  });

  it('Escape on a closed list is left alone', () => {
    const { trigger } = setup();
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    const escape = createEvent.keyDown(trigger, { key: 'Escape' });
    fireEvent(trigger, escape);
    document.removeEventListener('keydown', seen);
    expect(escape.defaultPrevented).toBe(false);
    expect(seen).toHaveBeenCalled();
  });

  it('Enter with nothing highlighted picks the first option', async () => {
    const { onChange, trigger } = setup();
    await userEvent.click(trigger);
    await userEvent.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith('apple');
  });

  it('Tab away closes the list without picking', async () => {
    const { onChange, trigger } = setup();
    await userEvent.click(trigger);
    await userEvent.keyboard('{ArrowDown}');
    await userEvent.tab();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'after' })).toHaveFocus();
  });

  it('clicking an option still picks it', async () => {
    const { onChange, trigger } = setup();
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole('option', { name: 'Banana' }));
    expect(onChange).toHaveBeenCalledWith('banana');
  });

  it('Home and End move the highlight to the first and last option', async () => {
    const { trigger } = setup();
    await userEvent.click(trigger);
    await userEvent.keyboard('{End}');
    expect(screen.getByRole('option', { name: 'Cherry' }).id).toBe(
      trigger.getAttribute('aria-activedescendant'),
    );
    await userEvent.keyboard('{Home}');
    expect(screen.getByRole('option', { name: 'Apple' }).id).toBe(
      trigger.getAttribute('aria-activedescendant'),
    );
  });

  it('scrolls the highlighted option into view', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      const { trigger } = setup();
      await userEvent.click(trigger);
      await userEvent.keyboard('{ArrowDown}{ArrowDown}');
      expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest' });
    } finally {
      // @ts-expect-error jsdom has no scrollIntoView; restore that
      delete Element.prototype.scrollIntoView;
    }
  });

  it('does not scroll the list when the pointer hovers an option', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      const { trigger } = setup();
      await userEvent.click(trigger);
      await userEvent.hover(screen.getByRole('option', { name: 'Cherry' }));
      expect(trigger.getAttribute('aria-activedescendant')).toBe(
        screen.getByRole('option', { name: 'Cherry' }).id,
      );
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      // @ts-expect-error jsdom has no scrollIntoView; restore that
      delete Element.prototype.scrollIntoView;
    }
  });

  it('builds option ids from the instance id and index, not the raw value', async () => {
    render(
      <Select id="odd" options={[{ value: 'a b/c', label: 'Odd' }]} onChange={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    expect(screen.getByRole('option').id).toBe('odd-option-0');
  });
});
