import type { Meta, StoryObj } from '@storybook/react';
import { IndexNotReadyScreen } from './IndexNotReadyScreen';

const meta = {
  title: 'Features/Search/IndexNotReadyScreen',
  component: IndexNotReadyScreen,
  parameters: { layout: 'fullscreen' },
  args: { onRetry: () => globalThis.console.log('retry') },
} satisfies Meta<typeof IndexNotReadyScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
