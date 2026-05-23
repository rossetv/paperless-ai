import type { Meta, StoryObj } from '@storybook/react';
import { Row } from './Row';

const meta = {
  title: 'Primitives/Row',
  component: Row,
  tags: ['autodocs'],
} satisfies Meta<typeof Row>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    label: 'Server URL',
    env: 'PAPERLESS_URL',
    hint: 'Base URL of your Paperless-ngx instance, reachable from this container.',
    controlId: 'demo-url',
    children: <input id="demo-url" placeholder="http://paperless.lan:8000" />,
  },
};

export const LastRow: Story = {
  args: {
    label: 'Log format',
    hint: 'JSON when you ship logs to an aggregator; console for local debugging.',
    last: true,
    children: <span>[ Console | JSON ]</span>,
  },
};
