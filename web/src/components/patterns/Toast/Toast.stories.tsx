import type { Meta, StoryObj } from '@storybook/react';
import { Toast } from './Toast';

const meta = {
  title: 'Patterns/Toast',
  component: Toast,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  decorators: [
    // The toast is position: fixed; a transform gives each story its own containing block.
    (Story) => (
      <div style={{ transform: 'translateZ(0)', minHeight: '20rem', width: '100%' }}>
        <Story />
      </div>
    ),
  ],
  argTypes: {
    variant: { control: { type: 'select' }, options: ['info', 'error'] },
    message: { control: 'text' },
    dismissAfterMs: { control: 'number' },
  },
} satisfies Meta<typeof Toast>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Info: Story = {
  args: {
    message: 'Indexing is in progress. New documents will appear shortly.',
    variant: 'info',
  },
};

export const Error: Story = {
  args: {
    message: 'Failed to connect to the search index. Please try again.',
    variant: 'error',
  },
};

export const WithDismissButton: Story = {
  args: {
    message: 'You can dismiss this notification manually.',
    variant: 'info',
    onDismiss: () => {
      /* story — noop */
    },
  },
};

export const AutoDismiss: Story = {
  args: {
    message: 'This notification auto-dismisses after 5 seconds.',
    variant: 'info',
    dismissAfterMs: 5000,
    onDismiss: () => {
      /* story — would unmount the toast in a real application */
    },
  },
};

export const LongUnbrokenText: Story = {
  args: {
    message:
      'Request failed: https://paperless.example.com/api/documents/12345/download/?original=true&token=abcdefghijklmnopqrstuvwxyz0123456789',
    variant: 'error',
    onDismiss: () => {
      /* story — noop */
    },
  },
};
