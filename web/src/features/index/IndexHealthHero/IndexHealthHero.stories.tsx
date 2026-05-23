import type { Meta, StoryObj } from '@storybook/react';
import { IndexHealthHero } from './IndexHealthHero';

const meta = {
  title: 'Features/Index/IndexHealthHero',
  component: IndexHealthHero,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof IndexHealthHero>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Healthy: Story = {
  args: {
    health: 'ok',
  },
};

export const Degraded: Story = {
  args: {
    health: 'degraded',
  },
};

export const Down: Story = {
  args: {
    health: 'down',
  },
};
