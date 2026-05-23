import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestConnectionRow } from './TestConnectionRow';

const meta = {
  title: 'Features/Settings/TestConnectionRow',
  component: TestConnectionRow,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof TestConnectionRow>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {
  args: { url: 'http://paperless.lan:8000', token: '••••3f9b', tokenIsMasked: true },
};
