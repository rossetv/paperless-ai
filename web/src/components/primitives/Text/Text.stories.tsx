import type { Meta, StoryObj } from '@storybook/react';
import { Text } from './Text';

const meta = {
  title: 'Primitives/Text',
  component: Text,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'select',
      options: ['body', 'body-emphasis', 'card-title', 'caption', 'caption-bold', 'micro'],
    },
    as: {
      control: 'select',
      options: ['p', 'span', 'strong', 'em', 'time', 'div'],
    },
    tone: {
      control: 'radio',
      options: [undefined, 'primary', 'secondary', 'tertiary'],
    },
  },
} satisfies Meta<typeof Text>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Body: Story = {
  args: {
    variant: 'body',
    children: 'The quick brown fox jumps over the lazy dog.',
  },
};

export const CardTitle: Story = {
  args: {
    variant: 'card-title',
    children: 'Boiler Warranty Certificate',
  },
};

export const Caption: Story = {
  args: {
    variant: 'caption',
    children: 'Secondary supporting text and metadata.',
  },
};

export const AllVariants: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-8)' }}>
      <Text variant="card-title">card-title — 21px bold</Text>
      <Text variant="body-emphasis">body-emphasis — 17px semibold</Text>
      <Text variant="body">body — 17px regular</Text>
      <Text variant="caption-bold">caption-bold — 14px semibold</Text>
      <Text variant="caption">caption — 14px regular</Text>
      <Text variant="micro">micro — 12px regular</Text>
    </div>
  ),
};
