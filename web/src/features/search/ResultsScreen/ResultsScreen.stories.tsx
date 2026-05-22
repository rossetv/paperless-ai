import type { Meta, StoryObj } from '@storybook/react';
import type { SearchResponse } from '../../../api/types';
import { ResultsScreen } from './ResultsScreen';

const RESPONSE: SearchResponse = {
  answer:
    'Across 2024 you paid Npower a total of £1,847.32 across twelve direct debits [1][2]. Your next collection is 5 February 2026 [1].',
  sources: [
    {
      document_id: 9823,
      title: 'Annual energy statement — 12 months to 31 Dec 2024',
      correspondent: 'Npower Energy',
      document_type: 'Statement',
      created: '2025-01-12',
      snippet: 'Total charges for the period: **£1,847.32**.',
      paperless_url: 'https://paperless.example.com/documents/9823/',
      score: 0.92,
    },
    {
      document_id: 9120,
      title: 'Direct debit confirmation — collection 12 of 12',
      correspondent: 'Npower Energy',
      document_type: 'Invoice',
      created: '2024-12-05',
      snippet: '**£153.94 was collected** on 5 December 2024.',
      paperless_url: 'https://paperless.example.com/documents/9120/',
      score: 0.86,
    },
  ],
  plan: {
    semantic_queries: [
      'Total annual energy payments to Npower in 2024',
      'Direct debit schedule and upcoming collection date',
    ],
    keyword_terms: ['Npower', 'direct debit', '2024'],
    sub_questions: [],
  },
  stats: { llm_calls: 3, latency_ms: 1842, refined: true },
};

/**
 * ResultsScreen embeds `FilterControls`, which drives `useFacets`. Storybook
 * does not wire TanStack Query, so this is a structural reference.
 */
const meta = {
  title: 'Features/Search/ResultsScreen',
  component: ResultsScreen,
  parameters: { layout: 'fullscreen' },
  args: {
    query: 'How much did I pay Npower across 2024?',
    filters: {
      tag_ids: [],
      correspondent_id: null,
      document_type_id: null,
      date_from: null,
      date_to: null,
    },
    result: RESPONSE,
    onFiltersChange: () => {},
    onCitationActivate: (i: number) => globalThis.console.log('cite', i),
    onPreview: (id: number) => globalThis.console.log('preview', id),
  },
} satisfies Meta<typeof ResultsScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const WithHighlightedSource: Story = {
  args: { highlightedIndex: 1 },
};
