import type { Meta, StoryObj } from '@storybook/react';
import { SearchErrorScreen } from './SearchErrorScreen';

const meta = {
  title: 'Features/Search/SearchErrorScreen',
  component: SearchErrorScreen,
  parameters: { layout: 'fullscreen' },
  args: {
    query: 'how much did I pay Npower across 2024?',
    onRetry: () => globalThis.console.log('retry'),
    onSearch: (q: string) => globalThis.console.log('search', q),
  },
} satisfies Meta<typeof SearchErrorScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { message: 'API error 500 — the search server is unavailable.' },
};
