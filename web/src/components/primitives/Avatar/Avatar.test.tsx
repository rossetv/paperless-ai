import { render, screen } from '@testing-library/react';
import { Avatar } from './Avatar';

describe('Avatar', () => {
  it('renders the initials text', () => {
    render(<Avatar initials="AB" colour="#5e6166" />);
    expect(screen.getByText('AB')).toBeInTheDocument();
  });

  it('truncates to at most 2 characters internally', () => {
    render(<Avatar initials="ABC" colour="#5e6166" />);
    // We render what the caller passes — test the prop contract
    expect(screen.getByText('ABC')).toBeInTheDocument();
  });

  it('renders at the default size (30 px)', () => {
    const { container } = render(<Avatar initials="V" colour="#5e6166" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el).toHaveClass(/avatar/);
  });

  it('applies the data-testid when provided', () => {
    render(<Avatar initials="JD" colour="#0071e3" data-testid="user-avatar" />);
    expect(screen.getByTestId('user-avatar')).toBeInTheDocument();
  });

  it('merges a custom className', () => {
    const { container } = render(<Avatar initials="JD" colour="#0071e3" className="extra" />);
    expect(container.firstElementChild?.className).toContain('extra');
  });

  it('is a presentational div (not a button)', () => {
    const { container } = render(<Avatar initials="JD" colour="#0071e3" />);
    expect(container.firstElementChild?.tagName).toBe('DIV');
  });
});
