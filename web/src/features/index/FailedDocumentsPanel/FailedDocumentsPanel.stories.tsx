import type { Meta, StoryObj } from '@storybook/react';
import { FailedDocumentsPanel } from './FailedDocumentsPanel';

const meta = {
  title: 'Features/Index/FailedDocumentsPanel',
  component: FailedDocumentsPanel,
  parameters: { layout: 'padded' },
  args: {
    onOpen: () => {},
  },
} satisfies Meta<typeof FailedDocumentsPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithFailures: Story = {
  args: {
    documents: [
      {
        document_id: 8421,
        title: 'Scanned receipt #2891 — illegible',
        failure_count: 3,
      },
      {
        document_id: 7188,
        title: null, // backend sends null when no indexed row exists
        failure_count: 1,
      },
    ],
  },
};

export const AllClear: Story = {
  args: {
    documents: [],
  },
};
