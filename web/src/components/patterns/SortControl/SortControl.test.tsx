import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SortControl } from './SortControl';

const OPTIONS = [
  { value: 'created', label: 'Date added' },
  { value: 'title', label: 'Title' },
  { value: 'correspondent', label: 'Correspondent' },
];

describe('SortControl', () => {
  it('renders the label and the selected option label on the trigger', () => {
    render(
      <SortControl
        id="sort"
        label="Sort"
        options={OPTIONS}
        value="created"
        onChange={() => {}}
      />,
    );
    const trigger = screen.getByRole('button');
    expect(trigger).toHaveTextContent('Sort');
    expect(trigger).toHaveTextContent('Date added');
  });

  it('the menu is closed initially', () => {
    render(
      <SortControl id="sort" label="Sort" options={OPTIONS} value="created" onChange={() => {}} />,
    );
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens the menu on trigger click and lists every option', async () => {
    render(
      <SortControl id="sort" label="Sort" options={OPTIONS} value="created" onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getAllByRole('menuitemradio')).toHaveLength(3);
  });

  it('marks the selected option with aria-checked', async () => {
    render(
      <SortControl id="sort" label="Sort" options={OPTIONS} value="title" onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(
      screen.getByRole('menuitemradio', { name: 'Title' }),
    ).toHaveAttribute('aria-checked', 'true');
    expect(
      screen.getByRole('menuitemradio', { name: 'Date added' }),
    ).toHaveAttribute('aria-checked', 'false');
  });

  it('calls onChange with the chosen value and closes the menu', async () => {
    const onChange = vi.fn();
    render(
      <SortControl id="sort" label="Sort" options={OPTIONS} value="created" onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Title' }));
    expect(onChange).toHaveBeenCalledWith('title');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes the menu on Escape', async () => {
    render(
      <SortControl id="sort" label="Sort" options={OPTIONS} value="created" onChange={() => {}} />,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  describe('menu keyboard model', () => {
    function setup(onChange = vi.fn()) {
      render(
        <SortControl id="sort" label="Sort" options={OPTIONS} value="title" onChange={onChange} />,
      );
      return { trigger: screen.getByRole('button'), onChange };
    }

    it('moves focus to the checked item on open', async () => {
      setup();
      await userEvent.click(screen.getByRole('button'));
      expect(screen.getByRole('menuitemradio', { name: 'Title' })).toHaveFocus();
    });

    it('Arrow Down and Up move between items and wrap', async () => {
      setup();
      await userEvent.click(screen.getByRole('button'));
      await userEvent.keyboard('{ArrowDown}');
      expect(screen.getByRole('menuitemradio', { name: 'Correspondent' })).toHaveFocus();
      await userEvent.keyboard('{ArrowDown}');
      expect(screen.getByRole('menuitemradio', { name: 'Date added' })).toHaveFocus();
      await userEvent.keyboard('{ArrowUp}');
      expect(screen.getByRole('menuitemradio', { name: 'Correspondent' })).toHaveFocus();
    });

    it('Home and End jump to the first and last item', async () => {
      setup();
      await userEvent.click(screen.getByRole('button'));
      await userEvent.keyboard('{End}');
      expect(screen.getByRole('menuitemradio', { name: 'Correspondent' })).toHaveFocus();
      await userEvent.keyboard('{Home}');
      expect(screen.getByRole('menuitemradio', { name: 'Date added' })).toHaveFocus();
    });

    it('Escape closes the menu, returns focus to the trigger and is default-prevented', async () => {
      const { trigger } = setup();
      await userEvent.click(trigger);
      const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      screen.getByRole('menuitemradio', { name: 'Title' }).dispatchEvent(event);
      await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
      expect(trigger).toHaveFocus();
      expect(event.defaultPrevented).toBe(true);
    });

    it('picking with Enter calls onChange and returns focus to the trigger', async () => {
      const { trigger, onChange } = setup();
      await userEvent.click(trigger);
      await userEvent.keyboard('{ArrowUp}{Enter}');
      expect(onChange).toHaveBeenCalledWith('created');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it('Tab closes the menu', async () => {
      setup();
      await userEvent.click(screen.getByRole('button'));
      await userEvent.tab();
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });

  it('merges a caller className onto the root', () => {
    const { container } = render(
      <SortControl
        id="sort"
        label="Sort"
        options={OPTIONS}
        value="created"
        onChange={() => {}}
        className="extra"
      />,
    );
    expect(container.firstChild).toHaveClass('extra');
  });
});
