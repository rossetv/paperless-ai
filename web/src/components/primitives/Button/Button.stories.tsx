import type { Meta, StoryObj } from '@storybook/react';
import { Button } from './Button';

const meta = {
  title: 'Primitives/Button',
  component: Button,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'radio',
      options: ['primary', 'secondary'],
    },
    size: {
      control: 'radio',
      options: ['default', 'small'],
    },
    disabled: { control: 'boolean' },
  },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Primary: Story = {
  args: {
    children: 'Buy',
    variant: 'primary',
  },
};

export const Secondary: Story = {
  args: {
    children: 'Learn more',
    variant: 'secondary',
  },
};

export const Small: Story = {
  args: {
    children: 'Small button',
    size: 'small',
  },
};

export const Disabled: Story = {
  args: {
    children: 'Unavailable',
    disabled: true,
  },
};

export const AllVariants: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-14)', alignItems: 'center' }}>
      <Button variant="primary">Primary</Button>
      <Button variant="secondary">Secondary</Button>
      <Button size="small">Small</Button>
      <Button disabled>Disabled</Button>
    </div>
  ),
};
