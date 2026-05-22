import type { Meta, StoryObj } from '@storybook/react';
import { PdfFrame } from './PdfFrame';

const meta = {
  title: 'Primitives/PdfFrame',
  component: PdfFrame,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
} satisfies Meta<typeof PdfFrame>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A blank src — Storybook only needs to show the framing. */
export const Default: Story = {
  args: { src: 'about:blank', title: 'Sample document PDF' },
  decorators: [
    (Story) => (
      <div style={{ height: '520px' }}>
        <Story />
      </div>
    ),
  ],
};
