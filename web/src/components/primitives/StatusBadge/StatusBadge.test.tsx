import { render, screen } from '@testing-library/react';
import { StatusBadge } from './StatusBadge';

describe('StatusBadge', () => {
  it('renders its label text', () => {
    render(<StatusBadge tone="ok">Active</StatusBadge>);
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('applies a tone-specific class', () => {
    render(<StatusBadge tone="danger">Suspended</StatusBadge>);
    expect(screen.getByText('Suspended').className).toMatch(/danger/);
  });

  it('renders a leading status dot element', () => {
    const { container } = render(<StatusBadge tone="ok">Active</StatusBadge>);
    expect(container.querySelector('[data-testid="status-dot"]')).toBeInTheDocument();
  });

  it('renders as a non-interactive <span>', () => {
    const { container } = render(<StatusBadge tone="warn">Idle</StatusBadge>);
    expect(container.firstElementChild?.tagName).toBe('SPAN');
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <StatusBadge tone="ok" className="extra">Active</StatusBadge>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
