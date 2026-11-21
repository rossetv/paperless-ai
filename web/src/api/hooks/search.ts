/** Search, facets, stats, library-list and recent-searches query hooks. */

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

/** Run a search query; disabled (stays `pending`) while `query` is empty. */
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
 * `placeholderData` keeps the previous page on screen while the next loads, so
 * paging does not flash an empty grid.
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
 * The signed-in user's recent searches — GET /api/recent-searches.
 *
 * `retry: false`: the idle screen treats any error as "no recent searches".
 */
export function useRecentSearches(): UseQueryResult<RecentSearchesResponse, Error> {
  return useQuery({
    queryKey: queryKeys.recentSearches(),
    queryFn: getRecentSearches,
    retry: false,
  });
}
