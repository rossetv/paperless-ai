import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { FilterRequest } from '../../api/types';
import { paramsToFilters } from './parseSearchParams';

/**
 * The empty filter state — no correspondent, no type, no tags, no date range.
 *
 * Re-exported so consuming components can reference a stable default without
 * duplicating the shape.
 */
export const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

/**
 * Emit a URLSearchParams with default-valued entries stripped, so the URL
 * stays short and `/` stays `/` until the user submits a query.
 */
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
  /** The current search query string (empty string when absent). */
  query: string;
  /** The current filter state, derived from the URL. */
  filters: FilterRequest;
  /**
   * Update the query; preserves the current filters.
   * Trims whitespace and omits the `q` param when the result is empty.
   */
  setQuery: (next: string) => void;
  /** Update the filters; preserves the current query. */
  setFilters: (next: FilterRequest) => void;
  /** The current search-string suffix (e.g. `?q=…`, including the `?`), or `''`. */
  searchString: string;
}

/**
 * URL ↔ {query, filters} binding for the search page.
 *
 * The search URL is the single source of truth for what the search page shows.
 * Defaults are stripped so `/` stays `/` until the user submits a query.
 * Param names are symmetric with `useLibraryUrlState` (q, type, corr, tag,
 * from, to) so the two can share bookmarkable filter URLs.
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
