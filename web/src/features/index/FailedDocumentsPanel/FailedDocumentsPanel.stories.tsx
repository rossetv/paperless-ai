import type { Meta, StoryObj } from '@storybook/react';
import { FailedDocumentsPanel } from './FailedDocumentsPanel';

const meta = {
  title: 'Features/Index/FailedDocumentsPanel',
  component: FailedDocumentsPanel,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
  args: {
    onRetry: () => {},
    onRetryAll: () => {},
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
        reason: 'OCR refused on all 3 model fallback attempts',
        failed_at: '2026-05-22T08:48:00Z',
      },
      {
        document_id: 7188,
        title: 'Encrypted PDF · password protected',
        reason: 'Page conversion failed: PDF requires password',
        failed_at: '2026-05-22T07:00:00Z',
      },
    ],
  },
};

export const Retrying: Story = {
  args: {
    ...WithFailures.args,
    retrying: true,
  },
};

export const AllClear: Story = {
  args: {
    documents: [],
  },
};
