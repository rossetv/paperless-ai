import type { Meta, StoryObj } from '@storybook/react';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from './SourceCard';

const source: SourceDocument = {
  document_id: 9823,
  title: 'Annual energy statement — 12 months to 31 Dec 2024',
  correspondent: 'Npower Energy',
  document_type: 'Statement',
  created: '2025-01-12',
  snippet:
    'Total electricity & gas charges for the period: **£1,847.32**. Twelve direct debits of **£153.94** were collected.',
  paperless_url: 'https://paperless.example.com/documents/9823/',
  score: 0.92,
  tags: [],
};

const meta = {
  title: 'Features/Search/SourceCard',
  component: SourceCard,
  parameters: { layout: 'padded' },
  args: { onPreview: (id: number) => console.log('preview', id) },
} satisfies Meta<typeof SourceCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { source, index: 2 } };

export const Highlighted: Story = {
  args: { source, index: 1, highlighted: true },
};
