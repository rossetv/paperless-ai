import type { Meta, StoryObj } from '@storybook/react';
import { ScopePill } from './ScopePill';

const meta = {
  title: 'Primitives/ScopePill',
  component: ScopePill,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  argTypes: { scope: { control: 'radio', options: ['api', 'mcp', 'admin'] } },
} satisfies Meta<typeof ScopePill>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Api: Story = { args: { scope: 'api' } };
export const Mcp: Story = { args: { scope: 'mcp' } };
export const Admin: Story = { args: { scope: 'admin' } };

export const AllScopes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-4)', alignItems: 'center' }}>
      <ScopePill scope="api" />
      <ScopePill scope="mcp" />
      <ScopePill scope="admin" />
    </div>
  ),
};
