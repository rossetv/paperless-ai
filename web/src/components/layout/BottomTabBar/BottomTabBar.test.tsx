import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { BottomTabBar } from './BottomTabBar';
import type { BottomTabItem } from './BottomTabBar';

const ITEMS: BottomTabItem[] = [
  { to: '/', label: 'Search', icon: 'search', end: true },
  { to: '/library', label: 'Library', icon: 'library' },
  { to: '/index', label: 'Index', icon: 'index' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
];

function renderBar(path = '/', items = ITEMS) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <BottomTabBar items={items} />
    </MemoryRouter>,
  );
}

describe('BottomTabBar', () => {
  it('renders a navigation landmark', () => {
    renderBar();
    expect(screen.getByRole('navigation', { name: /mobile navigation/i })).toBeInTheDocument();
  });

  it('renders a tab for every item', () => {
    renderBar();
    expect(screen.getAllByRole('link')).toHaveLength(4);
  });

  it('renders the label for each tab', () => {
    renderBar();
    expect(screen.getByText('Search')).toBeInTheDocument();
    expect(screen.getByText('Library')).toBeInTheDocument();
    expect(screen.getByText('Index')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('points each tab at its route', () => {
    renderBar();
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library');
    expect(screen.getByRole('link', { name: /index/i })).toHaveAttribute('href', '/index');
    expect(screen.getByRole('link', { name: /settings/i })).toHaveAttribute('href', '/settings');
  });

  it('marks the current route as active', () => {
    renderBar('/library');
    const libraryLink = screen.getByRole('link', { name: /library/i });
    expect(libraryLink.className).toMatch(/tab-active/);
  });

  it('does not mark non-current routes as active', () => {
    renderBar('/library');
    const indexLink = screen.getByRole('link', { name: /^index$/i });
    expect(indexLink.className).not.toMatch(/tab-active/);
  });

  it('marks root (/) active only when on / (end=true prevents false match)', () => {
    renderBar('/library');
    // Search uses end=true — should not be active on /library
    const searchLink = screen.getByRole('link', { name: /search/i });
    expect(searchLink.className).not.toMatch(/tab-active/);
  });

  it('marks the root link active when on /', () => {
    renderBar('/');
    const searchLink = screen.getByRole('link', { name: /search/i });
    expect(searchLink.className).toMatch(/tab-active/);
  });

  it('forwards a custom className', () => {
    const { container } = renderBar('/', ITEMS);
    render(
      <MemoryRouter>
        <BottomTabBar items={ITEMS} className="extra" />
      </MemoryRouter>,
    );
    const bars = document.querySelectorAll('[aria-label="Mobile navigation"]');
    // The second render has the extra class
    expect(bars[bars.length - 1]?.className).toContain('extra');
    // Suppress unused variable warning
    expect(container).toBeDefined();
  });

  it('renders no tabs when items is empty', () => {
    renderBar('/', []);
    const links = screen.queryAllByRole('link');
    expect(links).toHaveLength(0);
  });

  it('renders the aria-label on the nav element', () => {
    renderBar();
    expect(
      screen.getByRole('navigation', { name: 'Mobile navigation' }),
    ).toBeInTheDocument();
  });
});
