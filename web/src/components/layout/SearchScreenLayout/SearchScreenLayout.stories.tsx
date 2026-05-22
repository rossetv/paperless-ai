import type { Meta, StoryObj } from '@storybook/react';
import { SearchScreenLayout } from './SearchScreenLayout';

const meta = {
  title: 'Layout/SearchScreenLayout',
  component: SearchScreenLayout,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
} satisfies Meta<typeof SearchScreenLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Centred: Story = {
  args: {
    variant: 'centred',
    children: <p>A single centred content column.</p>,
  },
};

export const Rail: Story = {
  args: {
    variant: 'rail',
    rail: <aside>Filter rail</aside>,
    children: <p>Main content beside the rail.</p>,
  },
};
