import type { Meta, StoryObj } from '@storybook/react';
import { RoleBadge } from './RoleBadge';

const meta = {
  title: 'Primitives/RoleBadge',
  component: RoleBadge,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  argTypes: {
    role: { control: 'radio', options: ['admin', 'member', 'readonly', 'service'] },
  },
} satisfies Meta<typeof RoleBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Admin: Story = { args: { role: 'admin' } };
export const Member: Story = { args: { role: 'member' } };
export const ReadOnly: Story = { args: { role: 'readonly' } };
export const Service: Story = { args: { role: 'service' } };

export const AllRoles: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-6)', alignItems: 'center', flexWrap: 'wrap' }}>
      <RoleBadge role="admin" />
      <RoleBadge role="member" />
      <RoleBadge role="readonly" />
      <RoleBadge role="service" />
    </div>
  ),
};
