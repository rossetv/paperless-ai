import type { Meta, StoryObj } from '@storybook/react';
import { SaveBar } from './SaveBar';

const meta = {
  title: 'Features/Settings/SaveBar',
  component: SaveBar,
  tags: ['autodocs'],
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof SaveBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Hidden: Story = {
  args: {
    dirtyCount: 0,
    isPending: false,
    onDiscard: () => {},
    onSave: () => {},
  },
};

export const DirtyOne: Story = {
  args: {
    dirtyCount: 1,
    isPending: false,
    onDiscard: () => {},
    onSave: () => {},
  },
};

export const DirtyMany: Story = {
  args: {
    dirtyCount: 5,
    isPending: false,
    onDiscard: () => {},
    onSave: () => {},
  },
};

export const Saving: Story = {
  args: {
    dirtyCount: 3,
    isPending: true,
    onDiscard: () => {},
    onSave: () => {},
  },
};
