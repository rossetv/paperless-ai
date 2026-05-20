import type { Meta, StoryObj } from '@storybook/react';
import { Divider } from './Divider';

const meta = {
  title: 'Layout/Divider',
  component: Divider,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    decorative: { control: 'boolean' },
  },
} satisfies Meta<typeof Divider>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <div style={{ fontFamily: 'sans-serif', width: '300px' }}>
      <p>Content above the divider.</p>
      <Divider />
      <p>Content below the divider.</p>
    </div>
  ),
};

export const Decorative: Story = {
  args: {
    decorative: true,
  },
  render: (args) => (
    <div style={{ fontFamily: 'sans-serif', width: '300px' }}>
      <p>Above.</p>
      <Divider {...args} />
      <p>Below. (Divider is decorative — hidden from screen readers.)</p>
    </div>
  ),
};
