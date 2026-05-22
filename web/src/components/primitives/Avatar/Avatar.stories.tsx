import type { Meta, StoryObj } from '@storybook/react';
import { Avatar } from './Avatar';

const meta = {
  title: 'Primitives/Avatar',
  component: Avatar,
  parameters: { layout: 'centered' },
  tags: ['autodocs'],
  argTypes: {
    size: { control: { type: 'range', min: 20, max: 64, step: 2 } },
    colour: { control: 'color' },
  },
} satisfies Meta<typeof Avatar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { initials: 'AM', colour: 'linear-gradient(135deg,#5e6166,#2a2a2d)', size: 30 },
};

export const Small: Story = {
  args: { initials: 'V', colour: 'linear-gradient(135deg,#5e6166,#2a2a2d)', size: 26 },
};

export const Coloured: Story = {
  args: { initials: 'PK', colour: '#ff3b30', size: 30 },
};

export const AllSizes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-13)' }}>
      {([20, 26, 30, 40, 56] as const).map((s) => (
        <Avatar key={s} initials="AM" colour="linear-gradient(135deg,#5e6166,#2a2a2d)" size={s} />
      ))}
    </div>
  ),
};
