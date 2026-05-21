import type { Meta, StoryObj } from '@storybook/react';
import { Spinner } from './Spinner';

const meta = {
  title: 'Primitives/Spinner',
  component: Spinner,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    size: {
      control: 'radio',
      options: ['small', 'medium', 'large'],
    },
    label: { control: 'text' },
  },
} satisfies Meta<typeof Spinner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Small: Story = {
  args: { size: 'small' },
};

export const Medium: Story = {
  args: { size: 'medium' },
};

export const Large: Story = {
  args: { size: 'large' },
};

export const CustomLabel: Story = {
  args: { label: 'Searching documents…', size: 'medium' },
};

export const AllSizes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--spacing-14)', alignItems: 'center' }}>
      <Spinner size="small" label="Small spinner" />
      <Spinner size="medium" label="Medium spinner" />
      <Spinner size="large" label="Large spinner" />
    </div>
  ),
};
