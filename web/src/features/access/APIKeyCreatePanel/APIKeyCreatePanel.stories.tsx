import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { APIKeyCreatePanel } from './APIKeyCreatePanel';

const queryClient = new QueryClient();

const meta = {
  title: 'Access/APIKeyCreatePanel',
  component: APIKeyCreatePanel,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof APIKeyCreatePanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    onClose: () => {},
  },
};
