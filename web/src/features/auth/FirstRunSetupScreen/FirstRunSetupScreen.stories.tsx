import type { Meta, StoryObj } from '@storybook/react';
import { FirstRunSetupScreen } from './FirstRunSetupScreen';

/**
 * FirstRunSetupScreen drives the `useSetup` hook. Storybook does not wire
 * TanStack Query, so this story is a visual reference only.
 */
const meta = {
  title: 'Features/Auth/FirstRunSetupScreen',
  component: FirstRunSetupScreen,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof FirstRunSetupScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The dark first-run setup island. */
export const Default: Story = {};
