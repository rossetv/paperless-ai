import type { Meta, StoryObj } from '@storybook/react';
import { AnswerSurface } from './AnswerSurface';

const meta = {
  title: 'Primitives/AnswerSurface',
  component: AnswerSurface,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof AnswerSurface>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    sourceCount: 4,
    latencyMs: 1842,
    children:
      'Across 2024 you paid Npower a total of £1,847.32 across twelve direct debits.',
  },
};

export const Refined: Story = {
  args: {
    sourceCount: 4,
    latencyMs: 1842,
    refined: true,
    children:
      'Across 2024 you paid Npower a total of £1,847.32 across twelve direct debits.',
  },
};
