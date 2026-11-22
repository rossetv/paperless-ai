import React, { useState } from 'react';
import { createEvent, fireEvent, render, screen } from '@testing-library/react';
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

describe('FilterableListbox keyboard and semantics', () => {
  async function openIt(ui: React.ReactElement = <SingleHarness />) {
    render(ui);
    await userEvent.click(screen.getByRole('button', { name: /^(—|Apple)/ }));
    return screen.getByRole('combobox');
  }

  it('Escape on the open list closes it, is default-prevented and does not reach the document', async () => {
    const input = await openIt();
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    const escape = createEvent.keyDown(input, { key: 'Escape' });
    fireEvent(input, escape);
    document.removeEventListener('keydown', seen);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(escape.defaultPrevented).toBe(true);
    expect(seen).not.toHaveBeenCalled();
  });

  it('Enter with nothing highlighted picks the first visible option', async () => {
    const onSelect = vi.fn();
    await openIt(<SingleHarness onSelect={onSelect} />);
    await userEvent.keyboard('ban{Enter}');
    expect(onSelect).toHaveBeenCalledWith(3);
  });

  it('Enter with no matches and no highlight picks nothing', async () => {
    const onSelect = vi.fn();
    await openIt(<SingleHarness onSelect={onSelect} />);
    await userEvent.keyboard('zzz{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('Enter with nothing highlighted never fires the clear row', async () => {
    const onClear = vi.fn();
    const onSelect = vi.fn();
    await openIt(<SingleHarness initial={1} onClear={onClear} onSelect={onSelect} />);
    await userEvent.keyboard('apple{Enter}');
    expect(onClear).not.toHaveBeenCalled();
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('Enter right after opening, with no text and nothing highlighted, picks nothing', async () => {
    const onSelect = vi.fn();
    await openIt(<SingleHarness onSelect={onSelect} />);
    await userEvent.keyboard('{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('Enter with nothing highlighted does not pick over an offered Create row', async () => {
    const onSelect = vi.fn();
    const onCreate = vi.fn();
    await openIt(<SingleHarness onSelect={onSelect} onCreate={onCreate} />);
    await userEvent.keyboard('Ap{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('Enter with nothing highlighted still picks the first item when the text matches exactly', async () => {
    const onSelect = vi.fn();
    await openIt(<SingleHarness onSelect={onSelect} onCreate={vi.fn()} />);
    await userEvent.keyboard('apple{Enter}');
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('keeps the list out of the Tab order', async () => {
    await openIt();
    expect(screen.getByRole('listbox')).toHaveAttribute('tabindex', '-1');
  });

  it('a resting pointer entering a row under a keyboard scroll does not move the highlight', async () => {
    const input = await openIt();
    await userEvent.keyboard('{ArrowDown}');
    const before = input.getAttribute('aria-activedescendant');
    fireEvent.mouseEnter(screen.getByRole('option', { name: /Cherry/ }));
    fireEvent.mouseOver(screen.getByRole('option', { name: /Cherry/ }));
    expect(input.getAttribute('aria-activedescendant')).toBe(before);
  });

  it('the first mousemove after opening does not take the highlight, the next at new coordinates does', async () => {
    const input = await openIt();
    await userEvent.keyboard('{End}');
    const last = input.getAttribute('aria-activedescendant');
    const apple = screen.getByRole('option', { name: /Apple/ });
    fireEvent.mouseMove(apple, { clientX: 5, clientY: 5 });
    expect(input.getAttribute('aria-activedescendant')).toBe(last);
    fireEvent.mouseMove(apple, { clientX: 6, clientY: 5 });
    expect(input.getAttribute('aria-activedescendant')).toBe(apple.id);
  });

  it('a mousemove at the same coordinates after a keyboard move keeps the keyboard highlight', async () => {
    const input = await openIt();
    const apple = screen.getByRole('option', { name: /Apple/ });
    fireEvent.mouseMove(apple, { clientX: 5, clientY: 5 });
    await userEvent.keyboard('{End}');
    const last = input.getAttribute('aria-activedescendant');
    expect(last).not.toBe(apple.id);
    fireEvent.mouseMove(apple, { clientX: 5, clientY: 5 });
    expect(input.getAttribute('aria-activedescendant')).toBe(last);
    fireEvent.mouseMove(apple, { clientX: 6, clientY: 5 });
    expect(input.getAttribute('aria-activedescendant')).toBe(apple.id);
  });

  it('clicking the "No matches" text leaves the list open', async () => {
    const input = await openIt();
    await userEvent.keyboard('zzz');
    await userEvent.click(screen.getByText('No matches'));
    expect(screen.getByRole('combobox')).toBe(input);
    expect(input).toHaveFocus();
  });

  it('Escape returns focus to the trigger', async () => {
    await openIt();
    await userEvent.keyboard('{Escape}');
    expect(screen.getByRole('button')).toHaveFocus();
  });

  it('a single-select pick returns focus to the trigger', async () => {
    await openIt();
    await userEvent.keyboard('{ArrowDown}{Enter}');
    expect(screen.getByRole('button')).toHaveFocus();
  });

  it('Tab away closes the list without picking', async () => {
    const onSelect = vi.fn();
    await openIt(
      <>
        <SingleHarness onSelect={onSelect} />
        <button type="button">after</button>
      </>,
    );
    await userEvent.keyboard('{ArrowDown}');
    await userEvent.tab();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'after' })).toHaveFocus();
  });

  it('Home and End move the highlight once a row is highlighted', async () => {
    const input = await openIt();
    await userEvent.keyboard('{ArrowDown}{End}');
    expect(screen.getByRole('option', { name: /Cherry/ }).id).toBe(
      input.getAttribute('aria-activedescendant'),
    );
    await userEvent.keyboard('{Home}');
    expect(screen.getByRole('option', { name: /Apple/ }).id).toBe(
      input.getAttribute('aria-activedescendant'),
    );
  });

  it('scrolls the highlighted option into view', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      await openIt();
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
      const input = await openIt();
      const cherry = screen.getByRole('option', { name: /Cherry/ });
      fireEvent.mouseMove(cherry, { clientX: 1, clientY: 1 });
      fireEvent.mouseMove(cherry, { clientX: 2, clientY: 1 });
      expect(input.getAttribute('aria-activedescendant')).toBe(
        screen.getByRole('option', { name: /Cherry/ }).id,
      );
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      // @ts-expect-error jsdom has no scrollIntoView; restore that
      delete Element.prototype.scrollIntoView;
    }
  });

  it('marks the listbox multiselectable only in multi mode', async () => {
    await openIt();
    expect(screen.getByRole('listbox')).not.toHaveAttribute('aria-multiselectable');
    await userEvent.keyboard('{Escape}');
    render(
      <FilterableListbox<number>
        id="multi"
        items={ITEMS}
        value={[]}
        multiple
        triggerLabel="+ Add"
        onSelect={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '+ Add' }));
    expect(screen.getByRole('listbox')).toHaveAttribute('aria-multiselectable', 'true');
  });

  it('keeps the "No matches" text out of the listbox', async () => {
    await openIt();
    await userEvent.keyboard('zzz');
    const empty = screen.getByText('No matches');
    expect(empty.closest('[role="listbox"]')).toBeNull();
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('builds option ids from the instance and index, not the raw value', async () => {
    render(
      <FilterableListbox<string>
        id="odd"
        items={[{ value: 'a b/c', label: 'Odd' }]}
        value={null}
        triggerLabel="—"
        onSelect={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('option').id).not.toContain('a b/c');
    expect(screen.getByRole('option').id).toMatch(/^odd-option-.*0$/);
  });
});
