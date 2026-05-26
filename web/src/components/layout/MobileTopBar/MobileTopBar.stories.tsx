import type { Meta, StoryObj } from '@storybook/react';
import { MobileTopBar } from './MobileTopBar';

const meta = {
  title: 'Layout/MobileTopBar',
  component: MobileTopBar,
  parameters: {
    layout: 'fullscreen',
    /**
     * Force the viewport narrow enough to show the top bar — it is hidden on
     * desktop via media query. Set a small viewport in Storybook to preview.
     */
  },
  tags: ['autodocs'],
} satisfies Meta<typeof MobileTopBar>;

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
    Paperless<span style={{ opacity: 'var(--opacity-disabled)' }}>AI</span>
  </span>
);

/** Brand-only top bar. */
export const Default: Story = {
  args: {
    brand: <BrandMark />,
  },
  decorators: [
    (Story) => (
      <div style={{ background: 'var(--colour-bg)', minHeight: '200px' }}>
        <Story />
      </div>
    ),
  ],
};

/** Brand + action slot (UserMenu placeholder). */
export const WithActions: Story = {
  args: {
    brand: <BrandMark />,
    actions: (
      <button
        type="button"
        style={{
          width: 'var(--spacing-14)',
          height: 'var(--spacing-14)',
          borderRadius: 'var(--radius-circle)',
          background: 'var(--colour-overlay-dark)',
          border: 'none',
          color: 'var(--colour-text-on-dark)',
          fontSize: 'var(--font-size-nano)',
          cursor: 'pointer',
        }}
      >
        AM
      </button>
    ),
  },
  decorators: [
    (Story) => (
      <div style={{ background: 'var(--colour-bg)', minHeight: '200px' }}>
        <Story />
      </div>
    ),
  ],
};
