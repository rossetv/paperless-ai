import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { BottomTabBar } from './BottomTabBar';

const meta = {
  title: 'Layout/BottomTabBar',
  component: BottomTabBar,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/library']}>
        <div
          style={{
            background: 'var(--colour-bg)',
            minHeight: '200px',
            paddingBottom: 'calc(80px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          <Story />
        </div>
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof BottomTabBar>;

export default meta;
type Story = StoryObj<typeof meta>;

const ALL_TABS = [
  { to: '/', label: 'Search', icon: 'search' as const, end: true },
  { to: '/library', label: 'Library', icon: 'library' as const },
  { to: '/index', label: 'Index', icon: 'index' as const },
  { to: '/settings', label: 'Settings', icon: 'settings' as const },
];

/** All four tabs — Library is the active route. */
export const Default: Story = {
  args: {
    items: ALL_TABS,
  },
};

/** Three tabs — Settings omitted for a non-admin user. */
export const NonAdmin: Story = {
  args: {
    items: ALL_TABS.filter((t) => t.to !== '/settings'),
  },
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/']}>
        <div
          style={{
            background: 'var(--colour-bg)',
            minHeight: '200px',
            paddingBottom: 'calc(80px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          <Story />
        </div>
      </MemoryRouter>
    ),
  ],
};
