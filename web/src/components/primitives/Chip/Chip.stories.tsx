import type { Meta, StoryObj } from '@storybook/react';
import { Chip } from './Chip';

const meta = {
  title: 'Primitives/Chip',
  component: Chip,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    selected: { control: 'boolean' },
    onRemove: { action: 'removed' },
  },
} satisfies Meta<typeof Chip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: 'Invoice',
  },
};

export const Selected: Story = {
  args: {
    children: 'Invoice',
    selected: true,
  },
};

export const Removable: Story = {
  args: {
    children: 'Invoice',
    onRemove: () => undefined,
  },
};

export const RemovableSelected: Story = {
  args: {
    children: 'Invoice',
    selected: true,
    onRemove: () => undefined,
  },
};

export const AllVariants: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
      <Chip>Default</Chip>
      <Chip selected>Selected</Chip>
      <Chip onRemove={() => undefined}>Removable</Chip>
      <Chip selected onRemove={() => undefined}>Selected + Remove</Chip>
    </div>
  ),
};
