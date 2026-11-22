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

/** Narrow an untrusted URL sort string without casting it to the union. */
function isSortField(value: string): value is DocumentSortField {
  return (VALID_SORTS as ReadonlySet<string>).has(value);
}

function toPositiveInt(value: string | null): number | null {
  if (value === null) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

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

function paramsToView(params: URLSearchParams): LibraryView {
  return params.get('view') === 'list' ? 'list' : 'grid';
}

/** Default values are left out, so `/library` stays bare until a filter is set. */
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
  /** `replace` swaps the current history entry instead of adding one. */
  setQuery: (next: DocumentsQuery, options?: { replace?: boolean }) => void;
  setView: (next: LibraryView) => void;
  /** `?q=invoice&tag=5` style suffix, or `''`; for links that keep the parent state. */
  searchString: string;
}

/** Binds the library's DocumentsQuery and view toggle to the URL. */
export function useLibraryUrlState(): LibraryUrlState {
  const [searchParams, setSearchParams] = useSearchParams();

  const query = useMemo(() => paramsToQuery(searchParams), [searchParams]);
  const view = useMemo(() => paramsToView(searchParams), [searchParams]);

  const setQuery = useCallback(
    (next: DocumentsQuery, options?: { replace?: boolean }) => {
      setSearchParams(queryToParams(next, view), { replace: options?.replace === true });
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
