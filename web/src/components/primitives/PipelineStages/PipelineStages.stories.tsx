import type { Meta, StoryObj } from '@storybook/react';
import { PipelineStages } from './PipelineStages';

const meta = {
  title: 'Primitives/PipelineStages',
  component: PipelineStages,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof PipelineStages>;

export default meta;
type Story = StoryObj<typeof meta>;

export const MidPipeline: Story = {
  args: {
    stages: [
      { label: 'Planning the query', detail: '3 semantic queries, 5 keyword terms', state: 'done' },
      { label: 'Embedding & retrieving', detail: 'Vector + keyword search, RRF fusion', state: 'active' },
      { label: 'Synthesising the answer', detail: 'Final answer with citations', state: 'pending' },
    ],
  },
};
