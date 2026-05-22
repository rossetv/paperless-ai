import type { Meta, StoryObj } from '@storybook/react';
import { AppNavBar } from './AppNavBar';

/**
 * AppNavBar drives `useAuth` / `useLogout` and uses React-Router links.
 * Storybook does not wire TanStack Query or a router, so this story is a
 * visual reference only; behavioural coverage lives in the test suite.
 */
const meta = {
  title: 'Features/Shell/AppNavBar',
  component: AppNavBar,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof AppNavBar>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The authenticated app navigation bar. */
export const Default: Story = {
  decorators: [
    (Story) => (
      <div style={{ background: 'var(--colour-bg)', minHeight: 'var(--width-empty-state)' }}>
        <Story />
      </div>
    ),
  ],
};
