import type { Meta, StoryObj } from '@storybook/react';
import { LoginScreen } from './LoginScreen';

/** Storybook does not wire TanStack Query, so this is a visual reference only. */
const meta = {
  title: 'Features/Auth/LoginScreen',
  component: LoginScreen,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof LoginScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
