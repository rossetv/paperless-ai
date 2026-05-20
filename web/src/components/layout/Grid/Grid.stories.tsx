import type { Meta, StoryObj } from '@storybook/react';
import { Grid } from './Grid';

const meta = {
  title: 'Layout/Grid',
  component: Grid,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    columns: {
      control: 'radio',
      options: [1, 2, 3, 4, 5, 6],
    },
    gap: {
      control: 'select',
      options: [undefined, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
    },
  },
} satisfies Meta<typeof Grid>;

export default meta;
type Story = StoryObj<typeof meta>;

const Cell = ({ label }: { label: string }) => (
  <div
    style={{
      background: '#f5f5f7',
      border: '1px solid #d1d1d6',
      padding: '1rem',
      borderRadius: '8px',
      fontFamily: 'sans-serif',
      fontSize: '14px',
      textAlign: 'center',
    }}
  >
    {label}
  </div>
);

export const TwoColumns: Story = {
  args: {
    columns: 2,
    gap: 8,
    children: (
      <>
        <Cell label="Cell 1" />
        <Cell label="Cell 2" />
        <Cell label="Cell 3" />
        <Cell label="Cell 4" />
      </>
    ),
  },
};

export const ThreeColumns: Story = {
  args: {
    columns: 3,
    gap: 8,
    children: (
      <>
        <Cell label="Cell 1" />
        <Cell label="Cell 2" />
        <Cell label="Cell 3" />
        <Cell label="Cell 4" />
        <Cell label="Cell 5" />
        <Cell label="Cell 6" />
      </>
    ),
  },
};

export const NoGap: Story = {
  args: {
    columns: 3,
    children: (
      <>
        <Cell label="A" />
        <Cell label="B" />
        <Cell label="C" />
      </>
    ),
  },
};
