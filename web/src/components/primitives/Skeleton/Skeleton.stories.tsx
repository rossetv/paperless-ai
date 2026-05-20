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
    width: {
      control: 'radio',
      options: [undefined, 'full', 'wide', 'half', 'narrow'],
    },
    height: {
      control: 'radio',
      options: [undefined, 'line', 'control', 'block', 'media'],
    },
    lines: { control: { type: 'number', min: 1, max: 6 } },
  },
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const TextLine: Story = {
  args: { variant: 'text', width: 'wide' },
};

export const MultiLineText: Story = {
  args: { variant: 'text', lines: 4 },
};

export const Rectangular: Story = {
  args: { variant: 'rectangular', width: 'wide', height: 'block' },
};

export const Circular: Story = {
  args: { variant: 'circular' },
};

export const CardSkeleton: StoryObj = {
  // The wrapper sets layout only (a fixed-width Storybook canvas); the
  // skeletons themselves size entirely from the closed token-backed API.
  render: () => (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--spacing-6)',
        width: 'var(--width-empty-state)',
      }}
    >
      <Skeleton variant="rectangular" height="media" />
      <Skeleton variant="text" lines={3} />
    </div>
  ),
};
