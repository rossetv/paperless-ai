import { render, screen } from '@testing-library/react';
import { StatTile } from './StatTile';

describe('StatTile', () => {
  it('renders the value', () => {
    render(<StatTile value="14,238" label="Documents indexed" />);
    expect(screen.getByText('14,238')).toBeInTheDocument();
  });

  it('renders the label', () => {
    render(<StatTile value="14,238" label="Documents indexed" />);
    expect(screen.getByText('Documents indexed')).toBeInTheDocument();
  });

  it('renders a numeric value unchanged', () => {
    render(<StatTile value={842} label="Index size" />);
    expect(screen.getByText('842')).toBeInTheDocument();
  });

  it('renders the optional sub-line when given', () => {
    render(
      <StatTile value="14,238" label="Documents indexed" sub="+12 in the last cycle" />,
    );
    expect(screen.getByText('+12 in the last cycle')).toBeInTheDocument();
  });

  it('omits the sub-line when not given', () => {
    const { container } = render(<StatTile value="1" label="x" />);
    expect(container.querySelector('[data-testid="stat-tile-sub"]')).toBeNull();
  });

  it('applies the accent class when accent is set', () => {
    const { container } = render(
      <StatTile value="1" label="x" accent />,
    );
    const valueEl = container.querySelector('[data-testid="stat-tile-value"]');
    expect(valueEl?.className).toMatch(/accent/);
  });

  it('does not apply the accent class by default', () => {
    const { container } = render(<StatTile value="1" label="x" />);
    const valueEl = container.querySelector('[data-testid="stat-tile-value"]');
    expect(valueEl?.className).not.toMatch(/accent/);
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <StatTile value="1" label="x" className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
