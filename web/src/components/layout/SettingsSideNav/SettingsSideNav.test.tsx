import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
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

  it('scrolls to the hashed section once it mounts after the data loads', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    render(
      <MemoryRouter initialEntries={['/settings#search']}>
        <SettingsSideNav
          groups={[
            {
              title: 'Configuration',
              items: [{ id: 'search', label: 'Search Server', to: '/settings#search' }],
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(scrollTo).not.toHaveBeenCalled();

    const section = document.createElement('section');
    section.id = 'search';
    vi.spyOn(section, 'getBoundingClientRect').mockReturnValue({ top: 900 } as DOMRect);
    document.body.appendChild(section);
    await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1));
    expect(scrollTo).toHaveBeenCalledWith({ top: 900 - 140 });

    section.remove();
    scrollTo.mockRestore();
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

  const ANCHORS: SettingsNavGroup = {
    title: 'Configuration',
    items: [
      { id: 'search', label: 'Search', to: '/settings#search' },
      { id: 'logging', label: 'Logging', to: '/settings#logging' },
    ],
  };

  function HashButton(): React.ReactElement {
    const navigate = useNavigate();
    return (
      <button type="button" onClick={() => navigate('#logging')}>
        go
      </button>
    );
  }

  it('re-centres the active tab when the in-page hash changes', () => {
    const restore = mockStrip(1600, 997, 1100);
    try {
      render(
        <MemoryRouter initialEntries={['/settings#search']}>
          <HashButton />
          <SettingsSideNav groups={[ANCHORS]} />
        </MemoryRouter>,
      );
      const nav = screen.getByRole('navigation');
      nav.scrollLeft = 0;
      fireEvent.click(screen.getByRole('button', { name: 'go' }));
      expect(nav.scrollLeft).toBe(854);
    } finally {
      restore();
    }
  });

  it('re-centres the active tab when scrolling the page moves the scroll-spy', () => {
    const restore = mockStrip(1600, 997, 1100);
    const sections = ANCHORS.items.map((item) => {
      const el = document.createElement('section');
      el.id = item.id;
      document.body.append(el);
      return el;
    });
    const top = vi
      .spyOn(HTMLElement.prototype, 'offsetTop', 'get')
      .mockImplementation(function (this: HTMLElement) {
        return this.id === 'logging' ? 1000 : 0;
      });
    const height = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(5000);
    try {
      render(
        <MemoryRouter initialEntries={['/settings']}>
          <SettingsSideNav groups={[ANCHORS]} />
        </MemoryRouter>,
      );
      const nav = screen.getByRole('navigation');
      expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute('aria-current', 'page');
      nav.scrollLeft = 0;
      act(() => {
        window.scrollY = 1200;
        window.dispatchEvent(new Event('scroll'));
      });
      expect(screen.getByRole('link', { name: 'Logging' })).toHaveAttribute('aria-current', 'page');
      expect(nav.scrollLeft).toBe(854);
    } finally {
      window.scrollY = 0;
      top.mockRestore();
      height.mockRestore();
      sections.forEach((el) => el.remove());
      restore();
    }
  });
});
