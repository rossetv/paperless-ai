import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MatchCard } from './MatchCard';
import * as client from '../../../api/client';
import type { FilterRequest } from '../../../api/types';

function wrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

describe('MatchCard', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('uses cached search when available', () => {
    // staleTime: Infinity prevents background refetching of the primed cache entry,
    // so we can assert the network is not called at all.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    // Cache key shape: ['search', SearchRequest] — matches queryKeys.search(req) in hooks.ts.
    qc.setQueryData(['search', { query: 'invoice', filters: EMPTY_FILTERS }], {
      answer: '…',
      sources: [
        {
          document_id: 42,
          title: 't',
          snippet: 'foo **bar**',
          score: 0.9,
          correspondent: null,
          document_type: null,
          created: null,
          paperless_url: 'p',
          tags: [],
        },
      ],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 0, latency_ms: 0, refined: false },
    });
    const fetchStub = vi.spyOn(client, 'search');
    render(
      <MatchCard documentId={42} query="invoice" filters={EMPTY_FILTERS} />,
      { wrapper: wrapper(qc) },
    );
    expect(screen.getByText(/source 1 of 1/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.90/)).toBeInTheDocument();
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it('re-fetches when not in cache and renders the match', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, 'search').mockResolvedValue({
      answer: '…',
      sources: [
        {
          document_id: 42,
          title: 't',
          snippet: 'foo **bar**',
          score: 0.5,
          correspondent: null,
          document_type: null,
          created: null,
          paperless_url: 'p',
          tags: [],
        },
      ],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 0, latency_ms: 0, refined: false },
    });
    render(
      <MatchCard documentId={42} query="invoice" filters={EMPTY_FILTERS} />,
      { wrapper: wrapper(qc) },
    );
    await waitFor(() => expect(screen.getByText(/0\.50/)).toBeInTheDocument());
    expect(client.search).toHaveBeenCalledOnce();
  });

  it('renders honest "no match" when the search returns no row for this id', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, 'search').mockResolvedValue({
      answer: '…',
      sources: [
        {
          document_id: 999,
          title: 't',
          snippet: 's',
          score: 0.5,
          correspondent: null,
          document_type: null,
          created: null,
          paperless_url: 'p',
          tags: [],
        },
      ],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 0, latency_ms: 0, refined: false },
    });
    render(
      <MatchCard documentId={42} query="invoice" filters={EMPTY_FILTERS} />,
      { wrapper: wrapper(qc) },
    );
    await waitFor(() =>
      expect(screen.getByText(/didn't appear in the results/i)).toBeInTheDocument(),
    );
  });

  it('renders nothing when query is empty', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <MatchCard documentId={42} query="" filters={EMPTY_FILTERS} />,
      { wrapper: wrapper(qc) },
    );
    expect(container).toBeEmptyDOMElement();
  });
});
