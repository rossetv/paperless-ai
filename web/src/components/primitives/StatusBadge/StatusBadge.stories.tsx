import type { Meta, StoryObj } from '@storybook/react';
import { StatusBadge } from './StatusBadge';

const meta = {
  title: 'Primitives/StatusBadge',
  component: StatusBadge,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  argTypes: {
    tone: { control: 'radio', options: ['ok', 'warn', 'danger', 'info'] },
  },
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Active: Story = { args: { tone: 'ok', children: 'Active' } };
export const Suspended: Story = { args: { tone: 'danger', children: 'Suspended' } };
export const Expiring: Story = { args: { tone: 'warn', children: 'Expiring' } };

export const AllTones: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-6)', alignItems: 'center', flexWrap: 'wrap' }}>
      <StatusBadge tone="ok">Active</StatusBadge>
      <StatusBadge tone="warn">Expiring</StatusBadge>
      <StatusBadge tone="danger">Suspended</StatusBadge>
      <StatusBadge tone="info">Service</StatusBadge>
    </div>
  ),
};
