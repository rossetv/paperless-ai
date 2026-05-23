import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RebuildIndexCard } from './RebuildIndexCard';

/**
 * RebuildIndexCard owns the `useRebuildIndex` mutation, so the story wraps it
 * in a QueryClientProvider. The destructive POST is never reached in
 * Storybook — the confirmation flow can be exercised but the request fails
 * harmlessly with no backend.
 */
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
