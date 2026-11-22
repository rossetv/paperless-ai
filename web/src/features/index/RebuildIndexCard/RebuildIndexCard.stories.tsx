import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RebuildIndexCard } from './RebuildIndexCard';

/** With no backend in Storybook, the rebuild request fails harmlessly. */
const meta = {
  title: 'Features/Index/RebuildIndexCard',
  component: RebuildIndexCard,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof RebuildIndexCard>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The danger-zone card in its resting state. */
export const Default: Story = {};
