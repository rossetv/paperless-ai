import type { Meta, StoryObj } from '@storybook/react';
import { SearchErrorScreen } from './SearchErrorScreen';

const meta = {
  title: 'Features/Search/SearchErrorScreen',
  component: SearchErrorScreen,
  parameters: { layout: 'fullscreen' },
  args: { onRetry: () => globalThis.console.log('retry') },
} satisfies Meta<typeof SearchErrorScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { message: 'API error 500 — the search server is unavailable.' },
};
