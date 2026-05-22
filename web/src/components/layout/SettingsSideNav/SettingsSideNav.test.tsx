import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsSideNav } from './SettingsSideNav';
import type { SettingsNavGroup } from './SettingsSideNav';

const GROUPS: SettingsNavGroup[] = [
  {
    title: 'Access Control',
    items: [
      { id: 'users', label: 'Users', to: '/settings/users' },
      { id: 'keys', label: 'API Keys', to: '/settings/keys' },
    ],
  },
];

function renderNav(path = '/settings/users') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SettingsSideNav groups={GROUPS} />
    </MemoryRouter>,
  );
}

describe('SettingsSideNav', () => {
  it('renders a navigation landmark', () => {
    renderNav();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders each group title', () => {
    renderNav();
    expect(screen.getByText('Access Control')).toBeInTheDocument();
  });

  it('renders a link for every item', () => {
    renderNav();
    expect(screen.getByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'API Keys' })).toBeInTheDocument();
  });

  it('points each link at its route', () => {
    renderNav();
    expect(screen.getByRole('link', { name: 'Users' })).toHaveAttribute(
      'href',
      '/settings/users',
    );
  });

  it('marks the link matching the current route as current', () => {
    renderNav('/settings/keys');
    expect(screen.getByRole('link', { name: 'API Keys' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('does not mark a non-matching link as current', () => {
    renderNav('/settings/keys');
    expect(screen.getByRole('link', { name: 'Users' })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it('renders multiple groups when given more than one', () => {
    render(
      <MemoryRouter initialEntries={['/settings/users']}>
        <SettingsSideNav
          groups={[
            ...GROUPS,
            {
              title: 'Configuration',
              items: [{ id: 'llm', label: 'LLM Provider', to: '/settings/llm' }],
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('Configuration')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'LLM Provider' })).toBeInTheDocument();
  });

  it('forwards a custom className', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/settings/users']}>
        <SettingsSideNav groups={GROUPS} className="extra" />
      </MemoryRouter>,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
