import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { UserEditDrawer } from './UserEditDrawer';

const queryClient = new QueryClient();

const meta = {
  title: 'Access/UserEditDrawer',
  component: UserEditDrawer,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof UserEditDrawer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Create: Story = {
  args: { user: null, isSelf: false, onClose: () => {} },
};

export const Edit: Story = {
  args: {
    user: {
      id: 2,
      username: 'sam.patel',
      display_name: 'Sam Patel',
      email: 'sam@home.lan',
      role: 'member',
      status: 'active',
      created_at: '2026-01-01T00:00:00Z',
      last_login_at: '2026-05-20T00:00:00Z',
    },
    isSelf: false,
    onClose: () => {},
  },
};
