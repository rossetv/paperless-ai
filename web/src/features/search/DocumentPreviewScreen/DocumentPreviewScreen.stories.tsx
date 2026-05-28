import type { Meta, StoryObj } from '@storybook/react';
import { DocumentPreviewScreen } from './DocumentPreviewScreen';

/**
 * The in-app PDF viewer. The iframe points at the live `/api/documents/{id}/
 * pdf` proxy, which Storybook cannot serve — the chrome and sidebar are the
 * reference here.
 */
const meta = {
  title: 'Features/Search/DocumentPreviewScreen',
  component: DocumentPreviewScreen,
  parameters: { layout: 'fullscreen' },
  args: { onClose: () => globalThis.console.log('close') },
} satisfies Meta<typeof DocumentPreviewScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    source: {
      document_id: 9823,
      title: 'Annual energy statement — 12 months to 31 Dec 2024',
      correspondent: 'Npower Energy',
      document_type: 'Statement',
      created: '2025-01-12',
      snippet:
        'Twelve equal monthly direct debits of **£153.94** were collected, with a **£0.00** closing balance.',
      paperless_url: 'https://paperless.example.com/documents/9823/',
      score: 0.92,
      tags: ['Utilities', 'Energy', '2024', 'Statement'],
    },
    searchContext: { sourceIndex: 1, sourceCount: 4 },
  },
};

export const Standalone: Story = {
  args: {
    source: {
      document_id: 9823,
      title: 'Annual energy statement — 12 months to 31 Dec 2024',
      correspondent: 'Npower Energy',
      document_type: 'Statement',
      created: '2025-01-12',
      snippet: '',
      paperless_url: null,
      score: 0,
      tags: ['Utilities', 'Energy', '2024', 'Statement'],
    },
  },
};
