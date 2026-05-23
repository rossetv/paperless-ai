import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ViewToggle } from './ViewToggle';

describe('ViewToggle', () => {
  it('renders a Grid and a List option', () => {
    render(<ViewToggle value="grid" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Grid' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument();
  });

  it('marks the active option with aria-pressed', () => {
    render(<ViewToggle value="grid" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Grid' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'List' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('groups the buttons under an accessible group label', () => {
    render(<ViewToggle value="list" onChange={() => {}} />);
    expect(
      screen.getByRole('group', { name: /view/i }),
    ).toBeInTheDocument();
  });

  it('calls onChange with the clicked view', async () => {
    const onChange = vi.fn();
    render(<ViewToggle value="grid" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'List' }));
    expect(onChange).toHaveBeenCalledWith('list');
  });

  it('does not call onChange when the active option is clicked', async () => {
    const onChange = vi.fn();
    render(<ViewToggle value="grid" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Grid' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('merges a caller className onto the root group', () => {
    const { container } = render(
      <ViewToggle value="grid" onChange={() => {}} className="extra" />,
    );
    expect(container.firstChild).toHaveClass('extra');
  });
});
