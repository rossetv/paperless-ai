import { render, screen } from '@testing-library/react';
import { IndexHealthHero } from './IndexHealthHero';
import type { IndexHealthStatus } from '../../../api/types';

/**
 * Contract tests: IndexHealthHeroProps.health is `IndexHealthStatus`
 * ("ok" | "degraded" | "down") — the exact `wire.py` shape.
 */
describe('IndexHealthHero', () => {
  it('renders a healthy headline for the "ok" verdict', () => {
    render(<IndexHealthHero health={'ok' as IndexHealthStatus} />);
    expect(screen.getByText(/healthy/i)).toBeInTheDocument();
  });

  it('renders a degraded headline for the "degraded" verdict', () => {
    render(<IndexHealthHero health={'degraded' as IndexHealthStatus} />);
    expect(screen.getByText(/degraded/i)).toBeInTheDocument();
  });

  it('renders a down headline for the "down" verdict', () => {
    render(<IndexHealthHero health={'down' as IndexHealthStatus} />);
    expect(screen.getByText(/down/i)).toBeInTheDocument();
  });

  it('applies the healthy tone class for "ok"', () => {
    const { container } = render(<IndexHealthHero health="ok" />);
    const icon = container.querySelector('[data-testid="health-icon"]');
    expect(icon?.className).toMatch(/healthy/);
  });

  it('applies the unhealthy tone class for "degraded"', () => {
    const { container } = render(<IndexHealthHero health="degraded" />);
    const icon = container.querySelector('[data-testid="health-icon"]');
    expect(icon?.className).toMatch(/unhealthy/);
  });

  it('applies the unhealthy tone class for "down"', () => {
    const { container } = render(<IndexHealthHero health="down" />);
    const icon = container.querySelector('[data-testid="health-icon"]');
    expect(icon?.className).toMatch(/unhealthy/);
  });

  it('renders a <section> landmark', () => {
    const { container } = render(<IndexHealthHero health="ok" />);
    expect(container.querySelector('section')).toBeInTheDocument();
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <IndexHealthHero health="ok" className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
