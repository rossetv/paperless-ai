import type { Meta, StoryObj } from '@storybook/react';
import { NoResultsScreen } from './NoResultsScreen';
import type { SearchResponse } from '../../../api/types';

/**
 * NoResultsScreen embeds `FilterControls`, which drives `useFacets`.
 * Storybook does not wire TanStack Query, so this is a structural reference.
 */

const BASE_RESULT: SearchResponse = {
  answer: "I couldn't find any documents matching that query.",
  sources: [],
  plan: { specs: [] },
  stats: { llm_calls: 1, latency_ms: 120, refined: false },
  trace: { phases: [] },
  cost: {
    tokens: { prompt: 100, completion: 10, reasoning: 0, total: 110 },
    usd: 0.0001,
    local: false,
    llm_calls: 1,
  },
  outcome_kind: 'no_match',
  no_match_reason: 'empty_retrieval',
  candidate_count: null,
};

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

const meta = {
  title: 'Features/Search/NoResultsScreen',
  component: NoResultsScreen,
  parameters: { layout: 'fullscreen' },
  args: {
    result: BASE_RESULT,
    query: 'payslip from 2019 with a bonus over £4000',
    filters: EMPTY_FILTERS,
    onFiltersChange: () => {},
    onSearch: (q: string) => globalThis.console.log('search', q),
    onClearFilters: () => globalThis.console.log('clear filters'),
    onSearchWithoutFilters: () => globalThis.console.log('search no filters'),
    onPreview: (id: number) => globalThis.console.log('preview', id),
  },
} satisfies Meta<typeof NoResultsScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const JudgeRejected: Story = {
  args: {
    result: {
      ...BASE_RESULT,
      outcome_kind: 'no_match',
      no_match_reason: 'judge_rejected',
      candidate_count: 5,
    },
  },
};

export const WeakRelevance: Story = {
  args: {
    result: {
      ...BASE_RESULT,
      outcome_kind: 'no_match',
      no_match_reason: 'weak_relevance',
    },
  },
};

export const Clarify: Story = {
  args: {
    result: {
      ...BASE_RESULT,
      outcome_kind: 'clarify',
      answer: 'Your query is quite broad. Which year and correspondent are you interested in?',
      no_match_reason: null,
    },
  },
};
