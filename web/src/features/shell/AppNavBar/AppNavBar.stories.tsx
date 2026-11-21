import type { Meta, StoryObj } from '@storybook/react';
import { AppNavBar } from './AppNavBar';

/** Storybook does not wire TanStack Query or a router, so this is a visual reference only. */
const meta = {
  title: 'Features/Shell/AppNavBar',
  component: AppNavBar,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof AppNavBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  decorators: [
    (Story) => (
      <div style={{ background: 'var(--colour-bg)', minHeight: 'var(--width-empty-state)' }}>
        <Story />
      </div>
    ),
  ],
};
