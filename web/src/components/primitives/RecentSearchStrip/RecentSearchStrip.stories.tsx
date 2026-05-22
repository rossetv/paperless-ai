import type { Meta, StoryObj } from '@storybook/react';
import { RecentSearchStrip } from './RecentSearchStrip';

const meta = {
  title: 'Primitives/RecentSearchStrip',
  component: RecentSearchStrip,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
  args: { onSelect: (q: string) => globalThis.console.log('select', q) },
} satisfies Meta<typeof RecentSearchStrip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    items: [
      { query: "What's my npower invoice total for 2024?", time: '2h ago' },
      { query: 'Renewal date on the BUPA dental policy', time: 'yesterday' },
      { query: 'Show all contracts signed before March 2024', time: '2 days ago' },
      { query: 'Tax documents from my employer', time: 'last week' },
    ],
  },
};

export const Empty: Story = { args: { items: [] } };
