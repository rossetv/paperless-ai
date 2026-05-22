import type { Meta, StoryObj } from '@storybook/react';
import { IdleScreen } from './IdleScreen';

/**
 * IdleScreen drives `useRecentSearches` / `useStats`. Storybook does not wire
 * TanStack Query, so this story is a structural reference; behavioural
 * coverage lives in the test suite.
 */
const meta = {
  title: 'Features/Search/IdleScreen',
  component: IdleScreen,
  parameters: { layout: 'fullscreen' },
  args: { onSearch: (q: string) => globalThis.console.log('search', q) },
} satisfies Meta<typeof IdleScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
