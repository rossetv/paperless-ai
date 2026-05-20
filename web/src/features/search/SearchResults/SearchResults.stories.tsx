import type { Meta, StoryObj } from '@storybook/react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { SearchResponse } from '../../../api/types';
import { ApiError } from '../../../api/client';
import { SearchResults } from './SearchResults';

const successResponse: SearchResponse = {
  answer:
    'The boiler is a Vaillant EcoTec Plus 838, installed on 15 March 2021 [1]. ' +
    'Its warranty runs for five years [1].',
  sources: [
    {
      document_id: 1,
      title: 'Boiler Warranty Certificate',
      correspondent: 'Vaillant',
      document_type: 'Certificate',
      created: '2021-03-15',
      snippet:
        'The boiler model EcoTec Plus 838 was installed on 15 March 2021. ' +
        'The warranty covers parts and labour for five years.',
      paperless_url: 'https://paperless.example.com/documents/1/',
      score: 0.95,
    },
  ],
  plan: {
    semantic_queries: ['boiler model and installation date'],
    keyword_terms: ['boiler', 'warranty'],
    sub_questions: [],
  },
  stats: { llm_calls: 2, latency_ms: 540, refined: false },
};

/** Builds a UseQueryResult with pending defaults plus overrides. */
function makeResult(
  overrides: Partial<UseQueryResult<SearchResponse, Error>>,
): UseQueryResult<SearchResponse, Error> {
  return {
    data: undefined,
    error: null,
    isError: false,
    isPending: true,
    isFetching: false,
    isSuccess: false,
    status: 'pending',
    fetchStatus: 'idle',
    refetch: () => Promise.resolve({}),
    ...overrides,
  } as unknown as UseQueryResult<SearchResponse, Error>;
}

const meta = {
  title: 'Features/Search/SearchResults',
  component: SearchResults,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof SearchResults>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Loading — a search is in flight. */
export const Loading: Story = {
  args: {
    query: 'boiler',
    result: makeResult({ isPending: true, isFetching: true }),
    onCitationActivate: () => {
      /* story — noop */
    },
  },
};

/** Index initialising — the server replied 503 index-not-ready. */
export const Initialising: Story = {
  args: {
    query: 'boiler',
    result: makeResult({
      isError: true,
      isPending: false,
      status: 'error',
      error: new ApiError(503, 'index-not-ready'),
    }),
    onCitationActivate: () => {
      /* story — noop */
    },
  },
};

/** Search failed — a generic backend error. */
export const Failed: Story = {
  args: {
    query: 'boiler',
    result: makeResult({
      isError: true,
      isPending: false,
      status: 'error',
      error: new ApiError(500, 'internal server error'),
    }),
    onCitationActivate: () => {
      /* story — noop */
    },
  },
};

/** No results — the pipeline returned no source documents. */
export const NoResults: Story = {
  args: {
    query: 'nonexistent topic',
    result: makeResult({
      isSuccess: true,
      isPending: false,
      status: 'success',
      data: { ...successResponse, answer: '', sources: [] },
    }),
    onCitationActivate: () => {
      /* story — noop */
    },
  },
};

/** Success — answer, ranked sources, and the query-plan summary. */
export const Success: Story = {
  args: {
    query: 'boiler',
    result: makeResult({
      isSuccess: true,
      isPending: false,
      status: 'success',
      data: successResponse,
    }),
    onCitationActivate: () => {
      /* story — noop */
    },
  },
};
