import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { UsersScreen } from './UsersScreen';

// A query client whose `users` query is pre-seeded so the story renders the
// populated screen without a network.
const queryClient = new QueryClient();
queryClient.setQueryData(['users'], {
  users: [
    {
      id: 1,
      username: 'alex.morgan',
      display_name: 'Alex Morgan',
      email: 'alex@home.lan',
      role: 'admin',
      status: 'active',
      created_at: '2024-09-12T00:00:00Z',
      last_login_at: '2026-05-22T00:00:00Z',
    },
    {
      id: 2,
      username: 'sam.patel',
      display_name: 'Sam Patel',
      email: 'sam@home.lan',
      role: 'member',
      status: 'active',
      created_at: '2025-01-01T00:00:00Z',
      last_login_at: '2026-05-19T00:00:00Z',
    },
    {
      id: 6,
      username: 'pat.kim',
      display_name: 'Pat Kim',
      email: 'pat@home.lan',
      role: 'member',
      status: 'suspended',
      created_at: '2025-02-01T00:00:00Z',
      last_login_at: '2026-04-20T00:00:00Z',
    },
  ],
});

const meta = {
  title: 'Access/UsersScreen',
  component: UsersScreen,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/settings/users']}>
          <Story />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof UsersScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
