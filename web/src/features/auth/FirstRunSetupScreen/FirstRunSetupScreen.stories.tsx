import type { Meta, StoryObj } from '@storybook/react';
import { FirstRunSetupScreen } from './FirstRunSetupScreen';

/** Storybook does not wire TanStack Query, so this is a visual reference only. */
const meta = {
  title: 'Features/Auth/FirstRunSetupScreen',
  component: FirstRunSetupScreen,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof FirstRunSetupScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
