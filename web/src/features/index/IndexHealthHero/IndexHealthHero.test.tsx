import { render, screen } from '@testing-library/react';
import { IndexHealthHero } from './IndexHealthHero';
import type { IndexHealth } from '../../../api/types';

const HEALTHY: IndexHealth = {
  healthy: true,
  headline: 'Healthy · ready to serve',
  detail: 'Schema present · integrity check passed · last reconciled 4 minutes ago.',
  uptime: '14d 6h',
  since: '2026-05-07T00:00:00Z',
};

const UNHEALTHY: IndexHealth = {
  healthy: false,
  headline: 'Rebuilding · not ready',
  detail: 'The index is being rebuilt; the search server returns 503 until the first reconcile finishes.',
  uptime: '0d 0h',
  since: null,
};

describe('IndexHealthHero', () => {
  it('renders the headline', () => {
    render(<IndexHealthHero health={HEALTHY} />);
    expect(screen.getByText('Healthy · ready to serve')).toBeInTheDocument();
  });

  it('renders the detail line', () => {
    render(<IndexHealthHero health={HEALTHY} />);
    expect(screen.getByText(/integrity check passed/)).toBeInTheDocument();
  });

  it('renders the uptime figure', () => {
    render(<IndexHealthHero health={HEALTHY} />);
    expect(screen.getByText('14d 6h')).toBeInTheDocument();
  });

  it('renders the "since" date when present', () => {
    render(<IndexHealthHero health={HEALTHY} />);
    expect(screen.getByText(/since 7 May 2026/)).toBeInTheDocument();
  });

  it('omits the "since" line when the timestamp is null', () => {
    render(<IndexHealthHero health={UNHEALTHY} />);
    expect(screen.queryByText(/since/)).not.toBeInTheDocument();
  });

  it('applies the healthy tone class when healthy', () => {
    const { container } = render(<IndexHealthHero health={HEALTHY} />);
    const icon = container.querySelector('[data-testid="health-icon"]');
    expect(icon?.className).toMatch(/healthy/);
  });

  it('applies the unhealthy tone class when not healthy', () => {
    const { container } = render(<IndexHealthHero health={UNHEALTHY} />);
    const icon = container.querySelector('[data-testid="health-icon"]');
    expect(icon?.className).toMatch(/unhealthy/);
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <IndexHealthHero health={HEALTHY} className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
