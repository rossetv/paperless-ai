import type { Meta, StoryObj } from '@storybook/react';
import { IndexStatusFooter } from './IndexStatusFooter';

const meta = {
  title: 'Primitives/IndexStatusFooter',
  component: IndexStatusFooter,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof IndexStatusFooter>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    documentCount: 14238,
    chunkCount: 187612,
    embeddingModel: 'text-embedding-3-small',
  },
};
