import { render, screen } from '@testing-library/react';
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
