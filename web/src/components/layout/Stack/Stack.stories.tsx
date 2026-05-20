import type { Meta, StoryObj } from '@storybook/react';
import { Stack } from './Stack';

const meta = {
  title: 'Layout/Stack',
  component: Stack,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    direction: {
      control: 'radio',
      options: ['vertical', 'horizontal'],
    },
    gap: {
      control: 'select',
      options: [undefined, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
    },
    align: {
      control: 'radio',
      options: [undefined, 'start', 'center', 'end', 'stretch', 'baseline'],
    },
    justify: {
      control: 'radio',
      options: [undefined, 'start', 'center', 'end', 'between', 'around', 'evenly'],
    },
    wrap: { control: 'boolean' },
  },
} satisfies Meta<typeof Stack>;

export default meta;
type Story = StoryObj<typeof meta>;

const Box = ({ label }: { label: string }) => (
  <div
    style={{
      background: 'var(--colour-accent)',
      color: 'var(--colour-text-on-dark)',
      padding: 'var(--spacing-6) var(--spacing-11)',
      borderRadius: 'var(--radius-standard)',
      fontFamily: 'var(--font-text)',
      fontSize: 'var(--font-size-caption)',
    }}
  >
    {label}
  </div>
);

export const Vertical: Story = {
  args: {
    direction: 'vertical',
    gap: 6,
    children: (
      <>
        <Box label="Item 1" />
        <Box label="Item 2" />
        <Box label="Item 3" />
      </>
    ),
  },
};

export const Horizontal: Story = {
  args: {
    direction: 'horizontal',
    gap: 8,
    align: 'center',
    children: (
      <>
        <Box label="Item A" />
        <Box label="Item B" />
        <Box label="Item C" />
      </>
    ),
  },
};

export const SpaceBetween: Story = {
  args: {
    direction: 'horizontal',
    justify: 'between',
    children: (
      <>
        <Box label="Left" />
        <Box label="Right" />
      </>
    ),
  },
  decorators: [(Story) => <div style={{ width: 'var(--width-empty-state)' }}><Story /></div>],
};
