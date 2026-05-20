import type { Meta, StoryObj } from '@storybook/react';
import { Badge } from './Badge';

const meta = {
  title: 'Primitives/Badge',
  component: Badge,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'radio',
      options: ['neutral', 'accent', 'success', 'warning', 'danger'],
    },
  },
} satisfies Meta<typeof Badge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Neutral: Story = {
  args: {
    children: 'Draft',
    variant: 'neutral',
  },
};

export const Accent: Story = {
  args: {
    children: 'New',
    variant: 'accent',
  },
};

export const Success: Story = {
  args: {
    children: 'Indexed',
    variant: 'success',
  },
};

export const Warning: Story = {
  args: {
    children: 'Pending',
    variant: 'warning',
  },
};

export const Danger: Story = {
  args: {
    children: 'Error',
    variant: 'danger',
  },
};

export const Count: Story = {
  args: {
    children: 42,
    variant: 'accent',
  },
};

export const AllVariants: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
      <Badge variant="neutral">Neutral</Badge>
      <Badge variant="accent">Accent</Badge>
      <Badge variant="success">Success</Badge>
      <Badge variant="warning">Warning</Badge>
      <Badge variant="danger">Danger</Badge>
      <Badge variant="accent">{99}</Badge>
    </div>
  ),
};
