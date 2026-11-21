import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { FilterRequest } from '../../api/types';
import { paramsToFilters } from '../../lib/parseSearchParams';

export const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

/** Default values are omitted so `/` stays `/` until the user submits a query. */
function buildParams(query: string, filters: FilterRequest): URLSearchParams {
  const params = new URLSearchParams();
  if (query !== '') params.set('q', query);
  if (filters.document_type_id != null)
    params.set('type', String(filters.document_type_id));
  if (filters.correspondent_id != null)
    params.set('corr', String(filters.correspondent_id));
  for (const tag of filters.tag_ids) params.append('tag', String(tag));
  if (filters.date_from != null && filters.date_from !== '')
    params.set('from', filters.date_from);
  if (filters.date_to != null && filters.date_to !== '')
    params.set('to', filters.date_to);
  return params;
}

export interface SearchUrlState {
  query: string;
  filters: FilterRequest;
  /** Trims the query and keeps the current filters. */
  setQuery: (next: string) => void;
  /** Keeps the current query. */
  setFilters: (next: FilterRequest) => void;
  /** The current search string including the `?`, or `''`. */
  searchString: string;
}

/**
 * Binds the search page's query and filters to the URL, its single source of
 * truth. Param names match `useLibraryUrlState` so filter URLs carry across.
 */
export function useSearchUrlState(): SearchUrlState {
  const [searchParams, setSearchParams] = useSearchParams();

  const query = searchParams.get('q') ?? '';
  const filters = useMemo(() => paramsToFilters(searchParams), [searchParams]);

  const setQuery = useCallback(
    (next: string) => {
      setSearchParams(buildParams(next.trim(), filters));
    },
    [setSearchParams, filters],
  );

  const setFilters = useCallback(
    (next: FilterRequest) => {
      setSearchParams(buildParams(query, next));
    },
    [setSearchParams, query],
  );

  const searchString = searchParams.toString();
  return {
    query,
    filters,
    setQuery,
    setFilters,
    searchString: searchString === '' ? '' : `?${searchString}`,
  };
}
