import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestConnectionAction } from './TestConnectionAction';

const meta = {
  title: 'Features/Settings/TestConnectionAction',
  component: TestConnectionAction,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof TestConnectionAction>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {
  args: { url: 'http://paperless.lan:8000', token: '••••3f9b', tokenIsMasked: true },
};
