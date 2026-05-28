/**
 * Shared URL-parameter parser for search state.
 *
 * Extracted so both `useSearchUrlState` (the search page's live binding) and
 * `DocumentScreen` (which reads a frozen `parentSearch` string) derive
 * `{ query, filters }` from the same logic without duplication.
 */

import type { FilterRequest } from '../../api/types';

/** Parse a string into a positive integer, or null if not a positive int. */
function toPositiveInt(value: string | null): number | null {
  if (value === null) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Derive a `FilterRequest` from a `URLSearchParams`. */
export function paramsToFilters(params: URLSearchParams): FilterRequest {
  return {
    tag_ids: params
      .getAll('tag')
      .map((t) => Number.parseInt(t, 10))
      .filter((n) => Number.isFinite(n) && n > 0),
    correspondent_id: toPositiveInt(params.get('corr')),
    document_type_id: toPositiveInt(params.get('type')),
    date_from: params.get('from'),
    date_to: params.get('to'),
  };
}

export interface ParsedSearchParams {
  /** The query string (empty string when absent). */
  query: string;
  /** The filter state, derived from the URL params. */
  filters: FilterRequest;
}

/**
 * Parse a raw search-param string (e.g. `"?q=invoice&type=10"`) into
 * `{ query, filters }`.
 *
 * The leading `?` is stripped automatically if present. Returns empty-string
 * query and empty filters when the input is blank or contains no recognised
 * params.
 */
export function parseSearchParams(raw: string): ParsedSearchParams {
  const normalised = raw.startsWith('?') ? raw.slice(1) : raw;
  const params = new URLSearchParams(normalised);
  return {
    query: params.get('q') ?? '',
    filters: paramsToFilters(params),
  };
}
