import type { Meta, StoryObj } from '@storybook/react';
import type { SourceDocument } from '../../../api/types';
import { SourceList } from './SourceList';

const sources: SourceDocument[] = [
  {
    document_id: 1,
    title: 'Boiler Warranty Certificate',
    correspondent: 'Vaillant',
    document_type: 'Certificate',
    created: '2021-03-15',
    snippet: 'The boiler model EcoTec Plus 838 was installed on 15 March 2021. The warranty covers parts and labour for five years.',
    paperless_url: 'https://paperless.example.com/documents/1/',
    score: 0.95,
  },
  {
    document_id: 2,
    title: 'Council Tax Bill 2023',
    correspondent: 'Bradford Council',
    document_type: 'Invoice',
    created: '2023-04-01',
    snippet: 'Annual council tax bill for the period 1 April 2023 to 31 March 2024.',
    paperless_url: 'https://paperless.example.com/documents/2/',
    score: 0.87,
  },
  {
    document_id: 3,
    title: null,
    correspondent: null,
    document_type: null,
    created: null,
    snippet: 'Scanned document — only OCR text available.',
    paperless_url: 'https://paperless.example.com/documents/3/',
    score: 0.72,
  },
];

const meta = {
  title: 'Features/Search/SourceList',
  component: SourceList,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof SourceList>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Populated list with multiple sources. */
export const Populated: Story = {
  args: {
    sources,
  },
};

/** One source highlighted — simulates a CitationLink activation. */
export const WithHighlight: Story = {
  args: {
    sources,
    highlightedIndex: 2,
  },
};

/** Empty state — shown when the search returns no source documents. */
export const Empty: Story = {
  args: {
    sources: [],
  },
};
