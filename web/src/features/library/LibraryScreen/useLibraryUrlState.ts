import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { DocumentsQuery, DocumentSortField } from '../../../api/types';
import type { LibraryView } from '../../../components/patterns/ViewToggle/ViewToggle';

/** The library page size — must match the backend default. */
const PAGE_SIZE = 24;

/** The default query a fresh library URL represents. */
const DEFAULT_QUERY: DocumentsQuery = {
  page: 1,
  page_size: PAGE_SIZE,
  sort: 'added',
  descending: true,
  query: null,
  correspondent_id: null,
  document_type_id: null,
  tag_ids: [],
  date_from: null,
  date_to: null,
};

const DEFAULT_VIEW: LibraryView = 'grid';
const VALID_SORTS: ReadonlySet<DocumentSortField> = new Set([
  'added',
  'created',
  'title',
]);

/**
 * Narrow an untrusted URL sort string to a `DocumentSortField`. The widening to
 * `ReadonlySet<string>` is on the known-finite token set (no information lost),
 * which keeps the untrusted `value` typed as a plain string until this guard
 * validates it — rather than casting the URL input straight to the union.
 */
function isSortField(value: string): value is DocumentSortField {
  return (VALID_SORTS as ReadonlySet<string>).has(value);
}

/** Parse a string into a positive integer, or null if not a positive int. */
function toPositiveInt(value: string | null): number | null {
  if (value === null) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Derive a DocumentsQuery from a URLSearchParams. */
function paramsToQuery(params: URLSearchParams): DocumentsQuery {
  const sortRaw = params.get('sort');
  const sort: DocumentSortField =
    sortRaw !== null && isSortField(sortRaw) ? sortRaw : 'added';
  const page = toPositiveInt(params.get('page')) ?? 1;
  return {
    page,
    page_size: PAGE_SIZE,
    sort,
    descending: params.get('desc') !== '0',
    query: params.get('q'),
    correspondent_id: toPositiveInt(params.get('corr')),
    document_type_id: toPositiveInt(params.get('type')),
    tag_ids: params
      .getAll('tag')
      .map((t) => Number.parseInt(t, 10))
      .filter((n) => Number.isFinite(n) && n > 0),
    date_from: params.get('from'),
    date_to: params.get('to'),
  };
}

/** Derive the library view from a URLSearchParams. */
function paramsToView(params: URLSearchParams): LibraryView {
  return params.get('view') === 'list' ? 'list' : 'grid';
}

/**
 * Emit a URLSearchParams with default-valued entries stripped, so the URL
 * stays short and `/library` stays `/library` until a real filter is set.
 */
function queryToParams(
  query: DocumentsQuery,
  view: LibraryView,
): URLSearchParams {
  const params = new URLSearchParams();
  if (query.query != null && query.query !== '') params.set('q', query.query);
  if (query.document_type_id != null)
    params.set('type', String(query.document_type_id));
  if (query.correspondent_id != null)
    params.set('corr', String(query.correspondent_id));
  for (const tag of query.tag_ids) params.append('tag', String(tag));
  if (query.date_from != null && query.date_from !== '')
    params.set('from', query.date_from);
  if (query.date_to != null && query.date_to !== '')
    params.set('to', query.date_to);
  if (query.sort !== DEFAULT_QUERY.sort) params.set('sort', query.sort);
  if (!query.descending) params.set('desc', '0');
  if (query.page > 1) params.set('page', String(query.page));
  if (view !== DEFAULT_VIEW) params.set('view', view);
  return params;
}

export interface LibraryUrlState {
  query: DocumentsQuery;
  view: LibraryView;
  setQuery: (next: DocumentsQuery) => void;
  setView: (next: LibraryView) => void;
  /**
   * The current search-string suffix (e.g. `?q=invoice&tag=5`, including
   * the leading `?`, or `''` if no params). Useful for building nested
   * preview links that preserve the parent state.
   */
  searchString: string;
}

/**
 * URL ↔ DocumentsQuery + view-toggle binding for the library screen.
 *
 * The library URL is the single source of truth for what the library shows.
 * Reading derives the query and view from `useSearchParams`; writing strips
 * default values so URLs stay short.
 */
export function useLibraryUrlState(): LibraryUrlState {
  const [searchParams, setSearchParams] = useSearchParams();

  const query = useMemo(() => paramsToQuery(searchParams), [searchParams]);
  const view = useMemo(() => paramsToView(searchParams), [searchParams]);

  const setQuery = useCallback(
    (next: DocumentsQuery) => {
      setSearchParams(queryToParams(next, view));
    },
    [setSearchParams, view],
  );

  const setView = useCallback(
    (next: LibraryView) => {
      setSearchParams(queryToParams(query, next));
    },
    [setSearchParams, query],
  );

  const searchString = searchParams.toString();
  return {
    query,
    view,
    setQuery,
    setView,
    searchString: searchString === '' ? '' : `?${searchString}`,
  };
}
