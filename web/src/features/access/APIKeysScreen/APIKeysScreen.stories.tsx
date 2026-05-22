import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { APIKeysScreen } from './APIKeysScreen';

const queryClient = new QueryClient();
queryClient.setQueryData(['api-keys'], {
  keys: [
    {
      id: 1,
      name: 'Claude · MCP integration',
      key_prefix: 'sk-pls-aF82C',
      scopes: ['mcp', 'api'],
      owner_id: 1,
      owner_name: 'Alex Morgan',
      created_at: '2026-01-12T00:00:00Z',
      expires_at: null,
      last_used_at: '2026-05-22T09:00:00Z',
      revoked_at: null,
      request_count: 184602,
    },
    {
      id: 4,
      name: 'Legacy CRON script',
      key_prefix: 'sk-pls-dE03P',
      scopes: ['api'],
      owner_id: 1,
      owner_name: 'Alex Morgan',
      created_at: '2024-08-11T00:00:00Z',
      expires_at: '2020-01-01T00:00:00Z',
      last_used_at: '2024-09-01T00:00:00Z',
      revoked_at: null,
      request_count: 203,
    },
  ],
});

const meta = {
  title: 'Access/APIKeysScreen',
  component: APIKeysScreen,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/settings/keys']}>
          <Story />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof APIKeysScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
