/**
 * Tests for SearchResults.
 *
 * Verifies the result-state area renders the correct state for each phase of a
 * search: idle, loading, index-initialising (503), generic failure,
 * Unauthenticated (renders nothing — the page handles routing), no-results, and
 * a populated success response.
 */

import { render, screen } from '@testing-library/react';
import React from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { SearchResponse } from '../../../api/types';
import { ApiError, Unauthenticated } from '../../../api/client';
import { SearchResults } from './SearchResults';

// The composed sub-features are exercised in their own tests; here they are
// stubbed so SearchResults' state selection is tested in isolation.
vi.mock('../AnswerCard/AnswerCard', () => ({
  AnswerCard: ({ answer }: { answer: string }) =>
    React.createElement('div', { 'data-testid': 'answer-card' }, answer),
}));

vi.mock('../SourceList/SourceList', () => ({
  SourceList: ({
    sources,
    highlightedIndex,
  }: {
    sources: { document_id: number }[];
    highlightedIndex?: number;
  }) =>
    React.createElement(
      'div',
      { 'data-testid': 'source-list' },
      `sources:${sources.length} highlighted:${highlightedIndex ?? 'none'}`,
    ),
}));

vi.mock('../QueryPlanSummary/QueryPlanSummary', () => ({
  QueryPlanSummary: () =>
    React.createElement('div', { 'data-testid': 'query-plan-summary' }),
}));

/** Builds a UseQueryResult with sensible pending defaults plus overrides. */
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
    refetch: vi.fn(),
    ...overrides,
  } as unknown as UseQueryResult<SearchResponse, Error>;
}

const successResponse: SearchResponse = {
  answer: 'The boiler was installed in 2021 [1].',
  sources: [
    {
      document_id: 1,
      title: 'Boiler contract',
      correspondent: 'Company Ltd',
      document_type: 'Contract',
      created: '2021-01-01',
      snippet: 'boiler installation',
      paperless_url: 'https://paperless.example.com/documents/1/',
      score: 0.95,
    },
  ],
  plan: { semantic_queries: ['boiler'], keyword_terms: [], sub_questions: [] },
  stats: { llm_calls: 2, latency_ms: 500, refined: false },
};

describe('SearchResults', () => {
  it('renders nothing while the query is empty (idle)', () => {
    const { container } = render(
      <SearchResults
        query=""
        result={makeResult({})}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a loading spinner while a search is in flight', () => {
    render(
      <SearchResults
        query="boiler"
        result={makeResult({ isPending: true, isFetching: true })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows the initialising state on a 503 index-not-ready error', () => {
    render(
      <SearchResults
        query="boiler"
        result={makeResult({
          isError: true,
          isPending: false,
          error: new ApiError(503, 'index-not-ready'),
          status: 'error',
        })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(screen.getByText(/index is initialising/i)).toBeInTheDocument();
  });

  it('shows a search-failed state on a generic error', () => {
    render(
      <SearchResults
        query="boiler"
        result={makeResult({
          isError: true,
          isPending: false,
          error: new ApiError(500, 'boom'),
          status: 'error',
        })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(screen.getByText(/search failed/i)).toBeInTheDocument();
  });

  it('renders nothing for an Unauthenticated error (the page routes to login)', () => {
    const { container } = render(
      <SearchResults
        query="boiler"
        result={makeResult({
          isError: true,
          isPending: false,
          error: new Unauthenticated(),
          status: 'error',
        })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the empty state when a search returns no sources', () => {
    render(
      <SearchResults
        query="boiler"
        result={makeResult({
          isSuccess: true,
          isPending: false,
          status: 'success',
          data: { ...successResponse, answer: '', sources: [] },
        })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
      />,
    );
    expect(screen.getByText(/no results found/i)).toBeInTheDocument();
    expect(screen.queryByTestId('answer-card')).not.toBeInTheDocument();
  });

  it('renders the answer, sources and plan on a successful search', () => {
    render(
      <SearchResults
        query="boiler"
        result={makeResult({
          isSuccess: true,
          isPending: false,
          status: 'success',
          data: successResponse,
        })}
        onCitationActivate={vi.fn()} onPreview={vi.fn()}
        highlightedIndex={1}
      />,
    );
    expect(screen.getByTestId('answer-card')).toBeInTheDocument();
    expect(screen.getByTestId('source-list')).toHaveTextContent('highlighted:1');
    expect(screen.getByTestId('query-plan-summary')).toBeInTheDocument();
  });
});
