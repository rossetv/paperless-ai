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
      background: '#0071e3',
      color: '#fff',
      padding: '0.5rem 1rem',
      borderRadius: '8px',
      fontFamily: 'sans-serif',
      fontSize: '14px',
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
  decorators: [(Story) => <div style={{ width: '400px' }}><Story /></div>],
};
