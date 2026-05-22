import { render, screen } from '@testing-library/react';
import { StatCard } from './StatCard';

describe('StatCard', () => {
  it('renders the value', () => {
    render(<StatCard value={6} label="total accounts" />);
    expect(screen.getByText('6')).toBeInTheDocument();
  });

  it('renders the label', () => {
    render(<StatCard value={6} label="total accounts" />);
    expect(screen.getByText('total accounts')).toBeInTheDocument();
  });

  it('renders a string value unchanged', () => {
    render(<StatCard value="—" label="suspended" />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <StatCard value={1} label="x" className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
