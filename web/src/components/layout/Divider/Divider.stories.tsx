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
    orientation: {
      control: 'radio',
      options: ['horizontal', 'vertical'],
    },
    decorative: { control: 'boolean' },
  },
} satisfies Meta<typeof Divider>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Horizontal: Story = {
  render: () => (
    <div style={{ width: 'var(--width-empty-state)' }}>
      <p>Content above the divider.</p>
      <Divider />
      <p>Content below the divider.</p>
    </div>
  ),
};

export const Vertical: Story = {
  render: () => (
    <div style={{ display: 'flex', alignItems: 'center', height: 'var(--height-nav)' }}>
      <span>Left</span>
      <Divider orientation="vertical" />
      <span>Right</span>
    </div>
  ),
};

export const Decorative: Story = {
  args: {
    decorative: true,
  },
  render: (args) => (
    <div style={{ width: 'var(--width-empty-state)' }}>
      <p>Above.</p>
      <Divider {...args} />
      <p>Below. (Divider is decorative — hidden from screen readers.)</p>
    </div>
  ),
};
