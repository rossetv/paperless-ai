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

  it('matches exactly one anchor link as active on a hashed Settings page', () => {
    const CONFIG_GROUP: SettingsNavGroup = {
      title: 'Configuration',
      items: [
        { id: 'paperless', label: 'Paperless Connection', to: '/settings#paperless' },
        { id: 'llm', label: 'LLM Provider', to: '/settings#llm' },
        { id: 'search', label: 'Search Server', to: '/settings#search' },
      ],
    };
    render(
      <MemoryRouter initialEntries={['/settings#llm']}>
        <SettingsSideNav groups={[CONFIG_GROUP]} />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('link', { name: 'LLM Provider' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(
      screen.getByRole('link', { name: 'Paperless Connection' }),
    ).not.toHaveAttribute('aria-current');
    expect(
      screen.getByRole('link', { name: 'Search Server' }),
    ).not.toHaveAttribute('aria-current');
  });

  it('falls back to the first anchor as active when no hash is present', () => {
    const CONFIG_GROUP: SettingsNavGroup = {
      title: 'Configuration',
      items: [
        { id: 'paperless', label: 'Paperless Connection', to: '/settings#paperless' },
        { id: 'llm', label: 'LLM Provider', to: '/settings#llm' },
      ],
    };
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <SettingsSideNav groups={[CONFIG_GROUP]} />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('link', { name: 'Paperless Connection' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(
      screen.getByRole('link', { name: 'LLM Provider' }),
    ).not.toHaveAttribute('aria-current');
  });

  it('renders the eyebrow label when given', () => {
    render(
      <MemoryRouter initialEntries={['/settings/users']}>
        <SettingsSideNav groups={GROUPS} eyebrow="Settings" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('does not render an eyebrow element when none is given', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/settings/users']}>
        <SettingsSideNav groups={GROUPS} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[class*="eyebrow"]')).toBeNull();
  });

  /** Lays the strip out 390 wide with `scrollWidth` of content and the active tab at [left, right). */
  function mockStrip(scrollWidth: number, left: number, right: number): () => void {
    const rect = (l: number, r: number) =>
      ({ left: l, right: r, top: 0, bottom: 0, width: r - l, height: 0, x: l, y: 0 }) as DOMRect;
    const spies = [
      vi
        .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        .mockImplementation(function (this: HTMLElement) {
          if (this.tagName === 'NAV') return rect(0, 390);
          if (this.getAttribute('aria-current') === 'page') return rect(left, right);
          return rect(0, 80);
        }),
      vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(scrollWidth),
      vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(390),
    ];
    return () => spies.forEach((spy) => spy.mockRestore());
  }

  it('centres an off-screen active tab in the tab strip', () => {
    const restore = mockStrip(1600, 997, 1100);
    try {
      renderNav('/settings/keys');
      // Tab centre 1048.5 minus the strip's centre 195.
      expect(screen.getByRole('navigation').scrollLeft).toBe(854);
    } finally {
      restore();
    }
  });

  it('stops at the end of the strip when the active tab is the last one', () => {
    const restore = mockStrip(1150, 997, 1100);
    try {
      renderNav('/settings/keys');
      expect(screen.getByRole('navigation').scrollLeft).toBe(1150 - 390);
    } finally {
      restore();
    }
  });
});
