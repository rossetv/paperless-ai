import type { Meta, StoryObj } from '@storybook/react';
import { Skeleton } from './Skeleton';

const meta = {
  title: 'Primitives/Skeleton',
  component: Skeleton,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'radio',
      options: ['text', 'rectangular', 'circular'],
    },
    width: { control: 'text' },
    height: { control: 'text' },
  },
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const TextLine: Story = {
  args: { variant: 'text', width: '200px' },
};

export const Rectangular: Story = {
  args: { variant: 'rectangular', width: '300px', height: '80px' },
};

export const Circular: Story = {
  args: { variant: 'circular', width: '48px', height: '48px' },
};

export const CardSkeleton: StoryObj = {
  render: () => (
    <div style={{ width: '300px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <Skeleton variant="rectangular" height="160px" />
      <Skeleton variant="text" width="60%" />
      <Skeleton variant="text" width="80%" />
      <Skeleton variant="text" width="40%" />
    </div>
  ),
};
