import React, { useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { ViewToggle } from '../../../components/patterns/ViewToggle/ViewToggle';
import { SortControl } from '../../../components/patterns/SortControl/SortControl';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Button } from '../../../components/primitives/Button/Button';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { FilterControls } from '../../../components/patterns/FilterControls/FilterControls';
import { LibraryCard } from '../LibraryCard/LibraryCard';
import { useDocuments, useFacets } from '../../../api/hooks';
import { formatShortDate } from '../../../lib/formatDate';
import { useLibraryUrlState } from './useLibraryUrlState';
import type {
  DocumentsQuery,
  DocumentSortField,
  FilterRequest,
  TaxonomyEntry,
} from '../../../api/types';
import styles from './LibraryScreen.module.css';

/**
 * `added` sorts by `indexed_at`; `created` by the document's own date. Sorting
 * by correspondent needs backend support first (`_SORT_COLUMNS` and the
 * `Literal` in `routes.py`).
 */
const SORT_OPTIONS: ReadonlyArray<{ value: DocumentSortField; label: string }> = [
  { value: 'added', label: 'Date added' },
  { value: 'created', label: 'Document date' },
  { value: 'title', label: 'Title' },
];

/** Project the filter-only fields of a DocumentsQuery into a FilterRequest. */
function toFilterRequest(query: DocumentsQuery): FilterRequest {
  return {
    correspondent_id: query.correspondent_id ?? null,
    document_type_id: query.document_type_id ?? null,
    tag_ids: query.tag_ids,
    date_from: query.date_from ?? null,
    date_to: query.date_to ?? null,
  };
}

/** Find a taxonomy entry's display name by id; falls back to the raw id. */
function nameFor(entries: TaxonomyEntry[], id: number): string {
  return entries.find((e) => e.id === id)?.name ?? `#${id}`;
}

/**
 * True below SearchScreenLayout's 834px breakpoint, where the rail stacks above
 * the content. matchMedia is missing in some test environments.
 */
function isNarrowViewport(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(max-width: 834px)').matches
  );
}


/**
 * The Library browse screen. All state lives in the URL (`useLibraryUrlState`).
 * Opening a card keeps the search string so going back restores the query.
 *
 * Every change other than paging resets `page` to 1, so narrowing the results
 * never strands the user on an empty page.
 */
export function LibraryScreen(): React.ReactElement {
  const { query, view, setQuery, setView, searchString } = useLibraryUrlState();
  const navigate = useNavigate();

  const documents = useDocuments(query);
  const facets = useFacets();

  // On narrow viewports start the rail collapsed to keep the documents above
  // the fold. Read once at mount: it only concerns the initial layout.
  const [railDefaultExpanded] = React.useState(() => !isNarrowViewport());

  function submitSearch(text: string): void {
    setQuery({ ...query, query: text.trim() === '' ? null : text.trim(), page: 1 });
  }

  function applyFilters(filters: FilterRequest): void {
    setQuery({
      ...query,
      correspondent_id: filters.correspondent_id ?? null,
      document_type_id: filters.document_type_id ?? null,
      tag_ids: filters.tag_ids,
      date_from: filters.date_from ?? null,
      date_to: filters.date_to ?? null,
      page: 1,
    });
  }

  function changeSort(sort: DocumentSortField): void {
    setQuery({ ...query, sort, page: 1 });
  }

  function goToPage(page: number): void {
    setQuery({ ...query, page });
  }

  function clearAllFilters(): void {
    setQuery({
      ...query,
      query: null,
      correspondent_id: null,
      document_type_id: null,
      tag_ids: [],
      date_from: null,
      date_to: null,
      page: 1,
    });
  }

  // Active-filter chips, with ids resolved to names via the facets.
  const facetData = facets.data;
  const activeChips = useMemo(() => {
    const chips: Array<{ key: string; label: string; onRemove: () => void }> = [];
    if (query.query != null && query.query !== '') {
      chips.push({
        key: 'text',
        label: `“${query.query}”`,
        onRemove: () => setQuery({ ...query, query: null, page: 1 }),
      });
    }
    if (facetData === undefined) {
      return chips;
    }
    if (query.correspondent_id != null) {
      chips.push({
        key: 'correspondent',
        label: nameFor(facetData.correspondents, query.correspondent_id),
        onRemove: () =>
          setQuery({ ...query, correspondent_id: null, page: 1 }),
      });
    }
    if (query.document_type_id != null) {
      chips.push({
        key: 'document-type',
        label: nameFor(facetData.document_types, query.document_type_id),
        onRemove: () =>
          setQuery({ ...query, document_type_id: null, page: 1 }),
      });
    }
    for (const tagId of query.tag_ids) {
      chips.push({
        key: `tag-${tagId}`,
        label: nameFor(facetData.tags, tagId),
        onRemove: () =>
          setQuery({
            ...query,
            tag_ids: query.tag_ids.filter((id) => id !== tagId),
            page: 1,
          }),
      });
    }
    if (query.date_from != null && query.date_from !== '') {
      chips.push({
        key: 'date-from',
        label: `From ${formatShortDate(query.date_from)}`,
        onRemove: () => setQuery({ ...query, date_from: null, page: 1 }),
      });
    }
    if (query.date_to != null && query.date_to !== '') {
      chips.push({
        key: 'date-to',
        label: `To ${formatShortDate(query.date_to)}`,
        onRemove: () => setQuery({ ...query, date_to: null, page: 1 }),
      });
    }
    return chips;
  }, [facetData, query, setQuery]);

  // Stable so LibraryCard's React.memo is not defeated by a new arrow each render.
  const handleOpen = useCallback(
    (id: number) => {
      void navigate(`/library/document/${id}${searchString}`);
    },
    [navigate, searchString],
  );

  // Prefer the server-echoed page_size so the pager matches what was returned.
  const total = documents.data?.total ?? 0;
  const effectivePageSize = documents.data?.page_size ?? query.page_size;
  const pageCount = Math.max(1, Math.ceil(total / effectivePageSize));
  const rangeStart = total === 0 ? 0 : (query.page - 1) * effectivePageSize + 1;
  const rangeEnd =
    total === 0 ? 0 : Math.min(query.page * effectivePageSize, total);
  const hasFilters = activeChips.length > 0;
  const isFirstPage = query.page <= 1;
  const isLastPage = query.page >= pageCount;

  // Past the last page there is nothing to show: land on the last one without a history entry.
  const pastEnd = documents.data !== undefined && query.page > pageCount;
  useEffect(() => {
    if (pastEnd) {
      setQuery({ ...query, page: pageCount }, { replace: true });
    }
  }, [pastEnd, pageCount, query, setQuery]);

  const rail = (
    <FilterControls
      filters={toFilterRequest(query)}
      onFiltersChange={applyFilters}
      defaultExpanded={railDefaultExpanded}
    />
  );

  const header = (
    <div className={styles['header']}>
      <div className={styles['heading-block']}>
        <h1 className={styles['heading']}>Library</h1>
        <p className={styles['subheading']}>
          Every indexed document.{' '}
          <strong>{total.toLocaleString('en-GB')}</strong> total
          {total > 0 && (
            <>
              {' '}· showing {rangeStart.toLocaleString('en-GB')}–
              {rangeEnd.toLocaleString('en-GB')}
            </>
          )}
          .
        </p>
      </div>
      <div className={styles['header-controls']}>
        <ViewToggle value={view} onChange={setView} />
        <SortControl
          id="library-sort"
          label="Sort"
          options={SORT_OPTIONS}
          value={query.sort}
          onChange={changeSort}
        />
      </div>
    </div>
  );

  return (
    <SearchScreenLayout variant="rail" rail={rail} header={header}>
      <div className={styles['screen']}>
        {/* In-library search */}
        <SearchField
          key={query.query ?? ''}
          id="library-search"
          defaultValue={query.query ?? ''}
          allowEmpty
          placeholder="Filter library… (try title, correspondent, or document type)"
          onSubmit={submitSearch}
        />

        {/* Active-filter chip strip */}
        {activeChips.length > 0 && (
          <div className={styles['chip-strip']}>
            <span className={styles['chip-strip-label']}>Filtered by</span>
            {activeChips.map((chip) => (
              <Chip
                key={chip.key}
                selected
                onRemove={chip.onRemove}
                removeLabel={`Remove ${chip.label}`}
              >
                {chip.label}
              </Chip>
            ))}
            <button
              type="button"
              className={styles['clear-all']}
              onClick={clearAllFilters}
            >
              Clear all
            </button>
          </div>
        )}

        {/* Results */}
        {documents.isLoading ? (
          <div className={styles['state']}>
            <Spinner size="large" label="Loading documents" />
          </div>
        ) : documents.isError ? (
          <div className={styles['state']} role="alert">
            <EmptyState
              icon="warning"
              message="Could not load documents"
              description="The library list is unavailable. Try again in a moment."
              action={
                <Button variant="secondary" onClick={() => void documents.refetch()}>
                  Try again
                </Button>
              }
            />
          </div>
        ) : total === 0 ? (
          <div className={styles['state']}>
            {hasFilters ? (
              <EmptyState
                icon="search"
                message="No documents match"
                description="No documents match the current filters. Clear a filter to widen the results."
              />
            ) : (
              <EmptyState
                icon="search"
                message="The library is empty"
                description="Documents show up here once they have been indexed."
              />
            )}
          </div>
        ) : pastEnd ? null : (
          <>
            <div
              className={view === 'grid' ? styles['grid'] : styles['list']}
              data-view={view}
            >
              {(documents.data?.documents ?? []).map((doc) => (
                <LibraryCard
                  key={doc.id}
                  document={doc}
                  onOpen={handleOpen}
                  view={view}
                />
              ))}
            </div>

            {/* Pager */}
            <div className={styles['pager']}>
              <Button
                variant="secondary"
                disabled={isFirstPage}
                onClick={() => goToPage(query.page - 1)}
              >
                Previous
              </Button>
              <span className={styles['pager-status']}>
                Page {query.page.toLocaleString('en-GB')} of{' '}
                {pageCount.toLocaleString('en-GB')}
              </span>
              <Button
                variant="secondary"
                disabled={isLastPage}
                onClick={() => goToPage(query.page + 1)}
              >
                Next
              </Button>
            </div>
          </>
        )}
      </div>
    </SearchScreenLayout>
  );
}
