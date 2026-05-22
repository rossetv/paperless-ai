import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { APIKeyEditPanel } from './APIKeyEditPanel';

const queryClient = new QueryClient();

const meta = {
  title: 'Access/APIKeyEditPanel',
  component: APIKeyEditPanel,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof APIKeyEditPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    apiKey: {
      id: 7,
      name: 'CI token',
      key_prefix: 'sk-pls-aF82C',
      scopes: ['api', 'mcp'],
      owner_id: 1,
      owner_name: 'Alex Morgan',
      created_at: '2026-01-12T00:00:00Z',
      expires_at: null,
      last_used_at: '2026-05-22T09:00:00Z',
      revoked_at: null,
      request_count: 12,
    },
    onClose: () => {},
  },
};
