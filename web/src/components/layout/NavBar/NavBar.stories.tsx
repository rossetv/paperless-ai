import type { Meta, StoryObj } from '@storybook/react';
import { NavBar } from './NavBar';

const meta = {
  title: 'Layout/NavBar',
  component: NavBar,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof NavBar>;

export default meta;
type Story = StoryObj<typeof meta>;

const BrandMark = () => (
  <span
    style={{
      fontFamily: 'var(--font-display)',
      fontSize: '17px',
      fontWeight: 600,
      color: '#fff',
      letterSpacing: '-0.374px',
    }}
  >
    Paperless AI
  </span>
);

const NavActions = () => (
  <>
    <a
      href="/search"
      style={{
        color: '#fff',
        fontSize: '12px',
        textDecoration: 'none',
        fontFamily: 'var(--font-text)',
      }}
    >
      Search
    </a>
    <a
      href="/settings"
      style={{
        color: '#fff',
        fontSize: '12px',
        textDecoration: 'none',
        fontFamily: 'var(--font-text)',
      }}
    >
      Settings
    </a>
  </>
);

export const Default: Story = {
  args: {
    brand: <BrandMark />,
  },
  decorators: [
    (Story) => (
      <div style={{ background: '#f5f5f7', minHeight: '200px' }}>
        <Story />
        <div style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
          Page content scrolling behind the glass nav.
        </div>
      </div>
    ),
  ],
};

export const WithActions: Story = {
  args: {
    brand: <BrandMark />,
    actions: <NavActions />,
  },
  decorators: [
    (Story) => (
      <div style={{ background: '#f5f5f7', minHeight: '200px' }}>
        <Story />
        <div style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
          Page content scrolling behind the glass nav.
        </div>
      </div>
    ),
  ],
};

export const OnDarkBackground: Story = {
  args: {
    brand: <BrandMark />,
    actions: <NavActions />,
  },
  decorators: [
    (Story) => (
      <div style={{ background: '#000', minHeight: '200px' }}>
        <Story />
        <div style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff' }}>
          Dark section content — nav glass is still visible.
        </div>
      </div>
    ),
  ],
};
