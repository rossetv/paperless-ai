import type { Meta, StoryObj } from '@storybook/react';
import { SourceCardSurface } from './SourceCardSurface';

const meta = {
  title: 'Primitives/SourceCardSurface',
  component: SourceCardSurface,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof SourceCardSurface>;

export default meta;
type Story = StoryObj<typeof meta>;

const body = (
  <div>
    <strong style={{ fontFamily: 'var(--font-display)' }}>
      Annual energy statement
    </strong>
    <p>Twelve direct debits of £153.94 across 2024.</p>
  </div>
);

export const Default: Story = {
  args: { index: 2, thumbKind: 'statement', matched: [5, 6], children: body },
};

export const Highlighted: Story = {
  args: {
    index: 1,
    thumbKind: 'statement',
    matched: [3, 4, 7],
    highlighted: true,
    children: body,
  },
};
