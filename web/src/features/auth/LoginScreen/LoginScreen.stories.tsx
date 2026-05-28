import type { Meta, StoryObj } from '@storybook/react';
import { LoginScreen } from './LoginScreen';

/**
 * LoginScreen drives the `useLogin` hook. Storybook does not wire TanStack
 * Query, so these stories are a visual reference only; behavioural coverage
 * lives in the test suite.
 */
const meta = {
  title: 'Features/Auth/LoginScreen',
  component: LoginScreen,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof LoginScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The dark sign-in island. Dark in both light and dark themes. */
export const Default: Story = {};
