import type { Meta, StoryObj } from '@storybook/react';
import { RelevanceMeter } from './RelevanceMeter';

const meta = {
  title: 'Primitives/RelevanceMeter',
  component: RelevanceMeter,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof RelevanceMeter>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Strong: Story = { args: { tier: 'strong' } };
export const Good: Story = { args: { tier: 'good' } };
export const Partial: Story = { args: { tier: 'partial' } };
export const Weak: Story = { args: { tier: 'weak' } };
