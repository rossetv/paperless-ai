/**
 * Search, facets, stats, and recent-searches query hooks.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

import { useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import {
  search,
  getFacets,
  getStats,
  getDocuments,
  getRecentSearches,
} from '../client';
import type {
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  DocumentsQuery,
  DocumentsResponse,
  RecentSearchesResponse,
} from '../types';
import { queryKeys } from './keys';

/**
 * Execute a semantic search query.
 *
 * Disabled when `query` is empty so the hook stays in `pending` state without
 * issuing a request — avoids a pointless round-trip on initial render.
 */
export function useSearch(
  req: SearchRequest,
): UseQueryResult<SearchResponse, Error> {
  return useQuery({
    queryKey: queryKeys.search(req),
    queryFn: () => search(req),
    enabled: req.query.trim().length > 0,
  });
}

/** Fetch taxonomy facets for the filter panel. */
export function useFacets(): UseQueryResult<FacetsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.facets(),
    queryFn: getFacets,
  });
}

/** Fetch index statistics. */
export function useStats(): UseQueryResult<StatsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.stats(),
    queryFn: getStats,
  });
}

/**
 * Fetch a page of the library document list.
 *
 * `placeholderData` keeps the previous page on screen while the next page
 * loads — paging through the library does not flash an empty grid. The query
 * key includes the full `DocumentsQuery`, so changing any filter, the sort,
 * or the page produces a distinct cache entry.
 */
export function useDocuments(
  query: DocumentsQuery,
): UseQueryResult<DocumentsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.documents(query),
    queryFn: () => getDocuments(query),
    placeholderData: (previous) => previous,
  });
}

/**
 * The signed-in user's recent-search history — GET /api/recent-searches.
 *
 * Drives the idle search screen's "Recent searches" strip. `retry: false` so
 * a 401 (session gone) resolves to an error state at once rather than
 * retrying; the idle screen treats any error as "no recent searches" and
 * simply omits the strip.
 */
export function useRecentSearches(): UseQueryResult<RecentSearchesResponse, Error> {
  return useQuery({
    queryKey: queryKeys.recentSearches(),
    queryFn: getRecentSearches,
    retry: false,
  });
}
