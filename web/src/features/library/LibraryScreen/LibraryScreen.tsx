import React, { useMemo, useState } from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { ViewToggle } from '../../../components/patterns/ViewToggle/ViewToggle';
import type { LibraryView } from '../../../components/patterns/ViewToggle/ViewToggle';
import { SortControl } from '../../../components/patterns/SortControl/SortControl';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Button } from '../../../components/primitives/Button/Button';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { FilterControls } from '../../search/FilterControls/FilterControls';
import { LibraryCard } from '../LibraryCard/LibraryCard';
import { DocumentPreviewScreen } from '../../search/DocumentPreviewScreen/DocumentPreviewScreen';
import { useDocuments, useFacets } from '../../../api/hooks';
import type {
  DocumentsQuery,
  DocumentSortField,
  FilterRequest,
  TaxonomyEntry,
} from '../../../api/types';
import { cn } from '../../../lib/cn';
import styles from './LibraryScreen.module.css';

/** Page size for the library list — matches the backend default. */
const PAGE_SIZE = 24;

/**
 * The sort options offered by the SortControl.
 *
 * ``added`` sorts by ``indexed_at`` (date the document was added to the
 * index); ``created`` sorts by the document's own creation date.
 * ``correspondent`` is absent — the backend does not support it; if it is
 * needed in future, add it to ``_SORT_COLUMNS`` and the ``Literal`` in
 * ``routes.py`` first.
 */
const SORT_OPTIONS: ReadonlyArray<{ value: DocumentSortField; label: string }> = [
  { value: 'added', label: 'Date added' },
  { value: 'created', label: 'Document date' },
  { value: 'title', label: 'Title' },
];

/** The query a fresh Library screen starts from. */
const INITIAL_QUERY: DocumentsQuery = {
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
 * The Library browse screen.
 *
 * Owns a single `DocumentsQuery` and renders the header (title, total count,
 * result range), the in-library `SearchField`, the active-filter chip strip,
 * the `FilterControls` rail, the `ViewToggle` and `SortControl`, the document
 * grid/list of `LibraryCard`s, and a pager. When `previewDocumentId` is set,
 * it renders `DocumentPreviewScreen` as a full-bleed overlay (same pattern as
 * `SearchPage`).
 *
 * Every change other than paging resets `page` to 1 — narrowing the results
 * must never strand the user on a now-empty page. The `ViewToggle` is UI-only
 * state and does not touch the query.
 *
 * Tier: features/library (CODE_GUIDELINES §12.3) — composes layout, patterns,
 * primitives, sibling features, the api hooks and lib/. No `pages` import
 * target reaches these patterns directly; `LibraryPage` hosts this screen.
 */
export function LibraryScreen(): React.ReactElement {
  const [query, setQuery] = useState<DocumentsQuery>(INITIAL_QUERY);
  const [view, setView] = useState<LibraryView>('grid');
  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);

  const documents = useDocuments(query);
  const facets = useFacets();

  // ── Query mutators — each resets to page 1 except the pager. ──
  function submitSearch(text: string): void {
    setQuery((prev) => ({ ...prev, query: text.trim() === '' ? null : text.trim(), page: 1 }));
  }

  function applyFilters(filters: FilterRequest): void {
    setQuery((prev) => ({
      ...prev,
      correspondent_id: filters.correspondent_id ?? null,
      document_type_id: filters.document_type_id ?? null,
      tag_ids: filters.tag_ids,
      date_from: filters.date_from ?? null,
      date_to: filters.date_to ?? null,
      page: 1,
    }));
  }

  function changeSort(sort: DocumentSortField): void {
    setQuery((prev) => ({ ...prev, sort, page: 1 }));
  }

  function goToPage(page: number): void {
    setQuery((prev) => ({ ...prev, page }));
  }

  function clearAllFilters(): void {
    setQuery((prev) => ({
      ...prev,
      correspondent_id: null,
      document_type_id: null,
      tag_ids: [],
      date_from: null,
      date_to: null,
      page: 1,
    }));
  }

  // ── Active-filter chip strip — resolves ids to names via the facets. ──
  const facetData = facets.data;
  const activeChips = useMemo(() => {
    if (facetData === undefined) {
      return [];
    }
    const chips: Array<{ key: string; label: string; onRemove: () => void }> = [];
    if (query.correspondent_id != null) {
      chips.push({
        key: 'correspondent',
        label: nameFor(facetData.correspondents, query.correspondent_id),
        onRemove: () =>
          setQuery((prev) => ({ ...prev, correspondent_id: null, page: 1 })),
      });
    }
    if (query.document_type_id != null) {
      chips.push({
        key: 'document-type',
        label: nameFor(facetData.document_types, query.document_type_id),
        onRemove: () =>
          setQuery((prev) => ({ ...prev, document_type_id: null, page: 1 })),
      });
    }
    for (const tagId of query.tag_ids) {
      chips.push({
        key: `tag-${tagId}`,
        label: nameFor(facetData.tags, tagId),
        onRemove: () =>
          setQuery((prev) => ({
            ...prev,
            tag_ids: prev.tag_ids.filter((id) => id !== tagId),
            page: 1,
          })),
      });
    }
    if (query.date_from != null && query.date_from !== '') {
      chips.push({
        key: 'date-from',
        label: `From ${query.date_from}`,
        onRemove: () => setQuery((prev) => ({ ...prev, date_from: null, page: 1 })),
      });
    }
    if (query.date_to != null && query.date_to !== '') {
      chips.push({
        key: 'date-to',
        label: `To ${query.date_to}`,
        onRemove: () => setQuery((prev) => ({ ...prev, date_to: null, page: 1 })),
      });
    }
    return chips;
  }, [facetData, query]);

  // ── Derived paging values. ──
  // Use the server-echoed page_size when available so the pager is always
  // consistent with what was actually returned, not the locally-held constant.
  const total = documents.data?.total ?? 0;
  const effectivePageSize = documents.data?.page_size ?? query.page_size;
  const pageCount = Math.max(1, Math.ceil(total / effectivePageSize));
  const rangeStart = total === 0 ? 0 : (query.page - 1) * effectivePageSize + 1;
  const rangeEnd =
    total === 0 ? 0 : Math.min(query.page * effectivePageSize, total);
  const isFirstPage = query.page <= 1;
  const isLastPage = query.page >= pageCount;

  // Determine if a preview can be shown — requires an open id and document data.
  const previewDoc =
    previewDocumentId !== null
      ? documents.data?.documents.find((d) => d.id === previewDocumentId)
      : undefined;

  // When a preview is open, render DocumentPreviewScreen as a full-bleed
  // overlay — the same pattern SearchPage uses. Construct the SourceDocument
  // shape DocumentPreviewScreen expects; search-only fields (snippet, score)
  // get harmless defaults — Wave 7 reconciles the interface.
  if (previewDoc !== undefined) {
    const source = {
      document_id: previewDoc.id,
      title: previewDoc.title,
      correspondent: previewDoc.correspondent,
      document_type: previewDoc.document_type,
      created: previewDoc.created,
      snippet: '',
      score: 0,
      // LibraryDocument does not carry a deep-link URL; null tells the
      // DocumentViewerChrome to omit the "Open in Paperless" action.
      paperless_url: null,
    };
    return (
      <DocumentPreviewScreen
        source={source}
        onClose={() => setPreviewDocumentId(null)}
      />
    );
  }

  const rail = (
    <FilterControls
      filters={toFilterRequest(query)}
      onFiltersChange={applyFilters}
    />
  );

  return (
    <SearchScreenLayout variant="rail" rail={rail}>
      <div className={styles['screen']}>
        {/* ── Header ── */}
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
              options={[...SORT_OPTIONS]}
              value={query.sort}
              onChange={changeSort}
            />
          </div>
        </div>

        {/* ── In-library search ── */}
        <SearchField
          id="library-search"
          placeholder="Filter library… (try title, correspondent, or document type)"
          onSubmit={submitSearch}
        />

        {/* ── Active-filter chip strip ── */}
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

        {/* ── Results ── */}
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
            />
          </div>
        ) : total === 0 ? (
          <div className={styles['state']}>
            <EmptyState
              icon="search"
              message="No documents match"
              description="No documents match the current filters. Clear a filter to widen the results."
            />
          </div>
        ) : (
          <>
            <div
              className={cn(view === 'grid' ? styles['grid'] : styles['list'])}
              data-view={view}
            >
              {(documents.data?.documents ?? []).map((doc) => (
                <LibraryCard
                  key={doc.id}
                  document={doc}
                  onOpen={setPreviewDocumentId}
                />
              ))}
            </div>

            {/* ── Pager ── */}
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
