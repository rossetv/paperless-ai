import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RecentSearchStrip } from './RecentSearchStrip';

const items = [
  { query: 'npower invoice total 2024', time: '2h ago' },
  { query: 'BUPA dental renewal date', time: 'yesterday' },
];

describe('RecentSearchStrip', () => {
  it('renders a "Recent searches" heading', () => {
    render(<RecentSearchStrip items={items} onSelect={() => {}} />);
    expect(screen.getByText(/recent searches/i)).toBeInTheDocument();
  });

  it('renders every recent query', () => {
    render(<RecentSearchStrip items={items} onSelect={() => {}} />);
    expect(screen.getByText('npower invoice total 2024')).toBeInTheDocument();
    expect(screen.getByText('BUPA dental renewal date')).toBeInTheDocument();
  });

  it('renders the relative time for each item', () => {
    render(<RecentSearchStrip items={items} onSelect={() => {}} />);
    expect(screen.getByText('2h ago')).toBeInTheDocument();
    expect(screen.getByText('yesterday')).toBeInTheDocument();
  });

  it('calls onSelect with the query when a row is clicked', async () => {
    const onSelect = vi.fn();
    render(<RecentSearchStrip items={items} onSelect={onSelect} />);
    await userEvent.click(screen.getByText('npower invoice total 2024'));
    expect(onSelect).toHaveBeenCalledWith('npower invoice total 2024');
  });

  it('renders each row as a button', () => {
    render(<RecentSearchStrip items={items} onSelect={() => {}} />);
    expect(screen.getAllByRole('button')).toHaveLength(2);
  });

  it('renders nothing when there are no items', () => {
    const { container } = render(
      <RecentSearchStrip items={[]} onSelect={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('merges a custom className', () => {
    const { container } = render(
      <RecentSearchStrip items={items} onSelect={() => {}} className="extra" />,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
