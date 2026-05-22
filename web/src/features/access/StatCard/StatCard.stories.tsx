import type { Meta, StoryObj } from '@storybook/react';
import { StatCard } from './StatCard';

const meta = {
  title: 'Access/StatCard',
  component: StatCard,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof StatCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { value: 6, label: 'total accounts' } };

export const Row: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-10)' }}>
      <StatCard value={6} label="total accounts" />
      <StatCard value={4} label="active members" />
      <StatCard value={1} label="suspended" />
    </div>
  ),
};
