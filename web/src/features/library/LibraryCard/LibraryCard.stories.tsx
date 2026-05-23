import type { Meta, StoryObj } from '@storybook/react';
import { LibraryCard } from './LibraryCard';
import type { LibraryDocument } from '../../../api/types';

const DOC: LibraryDocument = {
  id: 1,
  title: 'Annual energy statement — 2024',
  correspondent: 'Npower Energy',
  document_type: 'Statement',
  created: '2025-01-12',
  tags: ['Energy', '2024'],
  page_count: 6,
};

const meta = {
  title: 'Features/Library/LibraryCard',
  component: LibraryCard,
  parameters: { layout: 'centered' },
  args: { onOpen: () => {} },
} satisfies Meta<typeof LibraryCard>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A statement-shaped document with two tags. */
export const Statement: Story = {
  args: { document: DOC },
};

/** An invoice-shaped document. */
export const Invoice: Story = {
  args: {
    document: { ...DOC, title: 'Direct debit confirmation #84', document_type: 'Invoice', tags: ['DD'] },
  },
};

/** A document with no title, no correspondent and no type. */
export const SparseMetadata: Story = {
  args: {
    document: { ...DOC, title: null, correspondent: null, document_type: null, created: null, tags: [] },
  },
};
