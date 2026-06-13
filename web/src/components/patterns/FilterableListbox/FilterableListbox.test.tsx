import React, { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterableListbox, type FilterableItem } from './FilterableListbox';

const ITEMS: FilterableItem<number>[] = [
  { value: 1, label: 'Apple', meta: '3 docs' },
  { value: 2, label: 'Apricot', meta: '1 doc' },
  { value: 3, label: 'Banana', meta: '7 docs' },
  { value: 4, label: 'Cherry', meta: '2 docs' },
];

/** Single-select harness threading `value` through state so re-renders are real. */
function SingleHarness(props: {
  onSelect?: (v: number) => void;
  onCreate?: (q: string) => void;
  onClear?: () => void;
  initial?: number | null;
}): React.ReactElement {
  const [value, setValue] = useState<number | null>(props.initial ?? null);
  const selectedItem = ITEMS.find((i) => i.value === value);
  return (
    <FilterableListbox<number>
      id="fruit"
      items={ITEMS}
      value={value}
      triggerLabel="—"
      selectedLabel={selectedItem?.label}
      clearOption={
        value !== null && props.onClear
          ? { label: 'Clear', onClear: props.onClear }
          : undefined
      }
      onSelect={(v) => {
        setValue(v);
        props.onSelect?.(v);
      }}
      onCreate={props.onCreate}
    />
  );
}

describe('FilterableListbox', () => {
  it('renders a closed trigger showing the selected label', () => {
    render(<SingleHarness initial={3} />);
    expect(screen.getByRole('button', { name: /banana/i })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('opens a combobox input and listbox when the trigger is clicked', async () => {
    render(<SingleHarness />);
    await userEvent.click(screen.getByRole('button'));
    const combobox = screen.getByRole('combobox');
    expect(combobox).toHaveAttribute('aria-expanded', 'true');
    const listbox = screen.getByRole('listbox');
    expect(combobox).toHaveAttribute('aria-controls', listbox.id);
  });

  it('filters options as the query is typed', async () => {
    render(<SingleHarness />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.type(screen.getByRole('combobox'), 'ap');
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent('Apple');
    expect(options[1]).toHaveTextContent('Apricot');
  });

  it('moves the highlight with ArrowDown/ArrowUp and reflects it in aria-activedescendant', async () => {
    render(<SingleHarness />);
    await userEvent.click(screen.getByRole('button'));
    const combobox = screen.getByRole('combobox');
    await userEvent.keyboard('{ArrowDown}');
    const first = screen.getByRole('option', { name: /Apple/ });
    expect(combobox).toHaveAttribute('aria-activedescendant', first.id);
    await userEvent.keyboard('{ArrowDown}');
    const second = screen.getByRole('option', { name: /Apricot/ });
    expect(combobox).toHaveAttribute('aria-activedescendant', second.id);
    await userEvent.keyboard('{ArrowUp}');
    expect(combobox).toHaveAttribute('aria-activedescendant', first.id);
  });

  it('wraps the highlight from last to first on ArrowDown', async () => {
    render(<SingleHarness />);
    await userEvent.click(screen.getByRole('button'));
    const combobox = screen.getByRole('combobox');
    // 4 items: down x4 lands on the last, a 5th wraps to the first.
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}');
    expect(combobox).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: /Apple/ }).id,
    );
  });

  it('selects the highlighted option with Enter and closes', async () => {
    const onSelect = vi.fn();
    render(<SingleHarness onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}'); // Apricot
    expect(onSelect).toHaveBeenCalledWith(2);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('selects an option on click', async () => {
    const onSelect = vi.fn();
    render(<SingleHarness onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('option', { name: /Cherry/ }));
    expect(onSelect).toHaveBeenCalledWith(4);
  });

  it('marks the selected option aria-selected', async () => {
    render(<SingleHarness initial={3} />);
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('option', { name: /Banana/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('option', { name: /Apple/ })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('closes on Escape without firing onSelect', async () => {
    const onSelect = vi.fn();
    render(<SingleHarness onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.keyboard('{ArrowDown}{Escape}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('closes on an outside pointer-down', async () => {
    render(
      <div>
        <SingleHarness />
        <button type="button">outside</button>
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: '—' }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('shows a Create row for an unmatched query and fires onCreate with the trimmed name', async () => {
    const onCreate = vi.fn();
    render(<SingleHarness onCreate={onCreate} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.type(screen.getByRole('combobox'), '  Durian  ');
    const createRow = screen.getByRole('option', { name: /Create/ });
    expect(createRow).toHaveTextContent('Create');
    await userEvent.click(createRow);
    expect(onCreate).toHaveBeenCalledWith('Durian');
  });

  it('hides the Create row when the query exactly matches an item (case-insensitive)', async () => {
    const onCreate = vi.fn();
    render(<SingleHarness onCreate={onCreate} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.type(screen.getByRole('combobox'), 'apple');
    expect(screen.queryByRole('option', { name: /Create/ })).not.toBeInTheDocument();
  });

  it('omits the Create row entirely when onCreate is not supplied', async () => {
    render(<SingleHarness />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.type(screen.getByRole('combobox'), 'zzz');
    expect(screen.queryByRole('option', { name: /Create/ })).not.toBeInTheDocument();
    expect(screen.getByText('No matches')).toBeInTheDocument();
  });

  it('fires the clear option when present and selected', async () => {
    const onClear = vi.fn();
    render(<SingleHarness initial={1} onClear={onClear} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('option', { name: 'Clear' }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('multi-select keeps the listbox open after a pick and accepts an array value', async () => {
    function MultiHarness(): React.ReactElement {
      const [selected, setSelected] = useState<number[]>([]);
      const available = ITEMS.filter((i) => !selected.includes(i.value));
      return (
        <FilterableListbox<number>
          id="tags"
          multiple
          items={available}
          value={selected}
          triggerLabel="+ Add"
          onSelect={(v) => setSelected((prev) => [...prev, v])}
        />
      );
    }
    render(<MultiHarness />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('option', { name: /Apple/ }));
    // Still open, and the picked item is gone from the offered set.
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Apple/ })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Banana/ })).toBeInTheDocument();
  });
});
