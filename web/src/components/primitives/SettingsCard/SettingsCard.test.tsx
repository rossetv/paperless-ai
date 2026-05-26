import { render, screen } from '@testing-library/react';
import { SettingsCard } from './SettingsCard';

describe('SettingsCard', () => {
  it('renders the title as a level-3 heading', () => {
    render(
      <SettingsCard title="Endpoint">
        <p>body</p>
      </SettingsCard>,
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Endpoint' })).toBeInTheDocument();
  });

  it('renders the subtitle when given', () => {
    render(
      <SettingsCard title="Endpoint" subtitle="Where the daemons reach Paperless.">
        <p>body</p>
      </SettingsCard>,
    );
    expect(screen.getByText('Where the daemons reach Paperless.')).toBeInTheDocument();
  });

  it('does not render a subtitle when none is given', () => {
    const { container } = render(
      <SettingsCard title="Endpoint">
        <p>body</p>
      </SettingsCard>,
    );
    // The only <p> should be the body text, not a subtitle.
    expect(container.querySelector('p')?.textContent).toBe('body');
  });

  it('renders children in the body', () => {
    render(
      <SettingsCard title="Endpoint">
        <p>rows here</p>
      </SettingsCard>,
    );
    expect(screen.getByText('rows here')).toBeInTheDocument();
  });

  it('renders the headerActions slot when given', () => {
    render(
      <SettingsCard
        title="Endpoint"
        headerActions={<button type="button">Test connection</button>}
      >
        <p>body</p>
      </SettingsCard>,
    );
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeInTheDocument();
  });

  it('does not render a header-actions container when no actions are given', () => {
    const { container } = render(
      <SettingsCard title="Endpoint">
        <p>body</p>
      </SettingsCard>,
    );
    // No element with header-actions class present.
    expect(container.querySelector('[class*="header-actions"]')).toBeNull();
  });

  it('forwards a custom className to the root', () => {
    const { container } = render(
      <SettingsCard title="Endpoint" className="extra">
        <p>body</p>
      </SettingsCard>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
