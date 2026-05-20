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
      fontSize: 'var(--font-size-body)',
      fontWeight: 'var(--font-weight-body-emphasis)',
      color: 'var(--colour-text-on-dark)',
      letterSpacing: 'var(--letter-spacing-body)',
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
        color: 'var(--colour-text-on-dark)',
        fontSize: 'var(--font-size-nav)',
        textDecoration: 'none',
        fontFamily: 'var(--font-text)',
      }}
    >
      Search
    </a>
    <a
      href="/settings"
      style={{
        color: 'var(--colour-text-on-dark)',
        fontSize: 'var(--font-size-nav)',
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
      <div style={{ background: 'var(--colour-bg)', minHeight: 'var(--width-empty-state)' }}>
        <Story />
        <div style={{ padding: 'var(--spacing-14)' }}>
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
      <div style={{ background: 'var(--colour-bg)', minHeight: 'var(--width-empty-state)' }}>
        <Story />
        <div style={{ padding: 'var(--spacing-14)' }}>
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
      <div style={{ background: 'var(--colour-surface-dark)', minHeight: 'var(--width-empty-state)' }}>
        <Story />
        <div style={{ padding: 'var(--spacing-14)', color: 'var(--colour-text-on-dark)' }}>
          Dark section content — nav glass is still visible.
        </div>
      </div>
    ),
  ],
};
