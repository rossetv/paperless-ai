import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { Button } from '../../primitives/Button/Button';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  it('renders the message', () => {
    render(<EmptyState icon="document" message="No documents found" />);
    expect(screen.getByText('No documents found')).toBeInTheDocument();
  });

  it('renders the icon', () => {
    render(<EmptyState icon="search" message="Nothing to show" />);
    // The Icon renders a Font Awesome <i class="fa-solid fa-magnifying-glass">.
    expect(document.querySelector('i.fa-magnifying-glass')).toBeInTheDocument();
  });

  it('renders the action element when action prop is provided', () => {
    render(
      <EmptyState
        icon="document"
        message="No results"
        action={<Button onClick={vi.fn()}>Start a search</Button>}
      />,
    );
    expect(screen.getByRole('button', { name: 'Start a search' })).toBeInTheDocument();
  });

  it('does not render an action when the action prop is omitted', () => {
    render(<EmptyState icon="document" message="No results" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('fires the action handler when the action is clicked', async () => {
    const handleClick = vi.fn();
    render(
      <EmptyState
        icon="document"
        message="Nothing here"
        action={<Button onClick={handleClick}>Do something</Button>}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Do something' }));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders an optional description when provided', () => {
    render(
      <EmptyState
        icon="search"
        message="No matches"
        description="Try adjusting your filters or search terms."
      />,
    );
    expect(
      screen.getByText('Try adjusting your filters or search terms.'),
    ).toBeInTheDocument();
  });

  it('does not render a description element when description is omitted', () => {
    render(<EmptyState icon="search" message="Nothing" />);
    // Only the message paragraph should be present; no second text block.
    expect(screen.queryByText(/try adjusting/i)).not.toBeInTheDocument();
  });
});
