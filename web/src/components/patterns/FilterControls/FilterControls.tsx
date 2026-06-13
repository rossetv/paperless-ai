import React from 'react';
import { FilterPanel } from '../FilterPanel/FilterPanel';
import { Select } from '../Select/Select';
import type { SelectOption } from '../Select/Select';
import { Chip } from '../../primitives/Chip/Chip';
import { Skeleton } from '../../primitives/Skeleton/Skeleton';
import { EmptyState } from '../EmptyState/EmptyState';
import { Input } from '../../primitives/Input/Input';
import { Button } from '../../primitives/Button/Button';
import { Stack } from '../../layout/Stack/Stack';
import { useFacets } from '../../../api/hooks';
import { useDebounce } from '../../../hooks/useDebounce';
import type { FilterRequest, TaxonomyEntry } from '../../../api/types';
import styles from './FilterControls.module.css';

/** Maximum number of unselected tags to show before the "Show all" toggle. */
const TAG_PAGE_SIZE = 12;

/** Debounce delay (ms) for the tag search input. */
const TAG_SEARCH_DEBOUNCE_MS = 200;

export interface FilterControlsProps {
  /**
   * The currently active filters. Controlled by the parent (SearchPage).
   * FilterControls reads the current state to reflect it in the controls.
   */
  filters: FilterRequest;
  /**
   * Called with the updated FilterRequest whenever the user changes a filter.
   * The parent is responsible for applying the new filters to the search.
   */
  onFiltersChange: (filters: FilterRequest) => void;
  /**
   * Whether the wrapping "Filters" panel starts expanded. Defaults to true
   * (open). Library passes `false` on narrow viewports so the rail collapses
   * behind the "Filters" toggle and the document list is not pushed below the
   * fold (UI-05).
   */
  defaultExpanded?: boolean;
}

/** Convert a TaxonomyEntry array into Select options. */
function toOptions(entries: TaxonomyEntry[]): SelectOption<string>[] {
  return entries.map((e) => ({ value: String(e.id), label: e.name }));
}

/**
 * Filter controls panel driven by the /api/facets endpoint.
 *
 * Lets the user narrow the search by correspondent, document type, tags,
 * and date range. The available options come from useFacets — so only
 * values actually present in the index are offered.
 *
 * Loading state: Skeleton placeholders replace the controls while facets load.
 * Empty state: controls are rendered (with no options) but remain operable.
 *
 * Tag picker behaviour:
 *   - Selected tags are always pinned at the top.
 *   - Up to TAG_PAGE_SIZE unselected tags are shown alphabetically.
 *   - When the total exceeds selected + TAG_PAGE_SIZE, a "Show all (N)"
 *     button expands the list into a scrollable region capped by
 *     --max-height-tag-picker so the date range is never pushed off screen.
 *   - A debounced text input filters the visible tag list by name.
 *
 * Connected pattern (DESIGN.md §11.1): a presentational pattern that is
 * permitted to import the api layer (useFacets / FilterRequest / TaxonomyEntry).
 * Shared by features/search and features/library.
 *
 * Composed from: FilterPanel, Select, Chip, Skeleton, Stack, Input, Button.
 */
export function FilterControls({
  filters,
  onFiltersChange,
  defaultExpanded = true,
}: FilterControlsProps): React.ReactElement {
  const { data: facets, isLoading, isError } = useFacets();

  // Tag search input — raw (undebounced) value drives the visible input.
  const [tagQuery, setTagQuery] = React.useState('');
  // Debounced query used for actual filtering.
  const debouncedQuery = useDebounce(tagQuery, TAG_SEARCH_DEBOUNCE_MS);
  // Whether the "Show all" state is active.
  const [expanded, setExpanded] = React.useState(false);

  function updateFilters(partial: Partial<FilterRequest>): void {
    onFiltersChange({ ...filters, ...partial });
  }

  function handleCorrespondentChange(value: string): void {
    updateFilters({ correspondent_id: value === '' ? null : parseInt(value, 10) });
  }

  function handleDocumentTypeChange(value: string): void {
    updateFilters({ document_type_id: value === '' ? null : parseInt(value, 10) });
  }

  function handleTagToggle(tagId: number): void {
    const current = filters.tag_ids;
    const next = current.includes(tagId)
      ? current.filter((id) => id !== tagId)
      : [...current, tagId];
    updateFilters({ tag_ids: next });
  }

  function handleDateFromChange(e: React.ChangeEvent<HTMLInputElement>): void {
    updateFilters({ date_from: e.target.value !== '' ? e.target.value : null });
  }

  function handleDateToChange(e: React.ChangeEvent<HTMLInputElement>): void {
    updateFilters({ date_to: e.target.value !== '' ? e.target.value : null });
  }

  function handleTagQueryChange(e: React.ChangeEvent<HTMLInputElement>): void {
    setTagQuery(e.target.value);
  }

  if (isError) {
    return (
      <div role="alert">
        <EmptyState
          icon="warning"
          message="Filters are unavailable"
          description="Could not load filter options. You can still search without filters."
        />
      </div>
    );
  }

  if (isLoading || facets === undefined) {
    return (
      <Stack direction="vertical" gap={6}>
        <Skeleton variant="rectangular" height="control" />
        <Skeleton variant="rectangular" height="control" />
        <Skeleton variant="rectangular" height="control" />
      </Stack>
    );
  }

  const correspondentOptions = toOptions(facets.correspondents);
  const documentTypeOptions = toOptions(facets.document_types);
  const selectedCorrespondentValue =
    filters.correspondent_id != null ? String(filters.correspondent_id) : undefined;
  const selectedDocumentTypeValue =
    filters.document_type_id != null ? String(filters.document_type_id) : undefined;

  // ── Tag picker logic ─────────────────────────────────────────────────────

  // All tags sorted alphabetically for consistency.
  const allTagsSorted = [...facets.tags].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  // Tags the user has selected (always pinned at top, regardless of filter).
  const selectedTags = allTagsSorted.filter((t) => filters.tag_ids.includes(t.id));

  // Unselected tags that match the current search query.
  const query = debouncedQuery.trim().toLowerCase();
  const unselectedFiltered = allTagsSorted.filter(
    (t) =>
      !filters.tag_ids.includes(t.id) &&
      (query === '' || t.name.toLowerCase().includes(query)),
  );

  // How many unselected tags are hidden behind the toggle.
  const hiddenCount = Math.max(0, unselectedFiltered.length - TAG_PAGE_SIZE);
  const needsToggle = hiddenCount > 0;

  // Chips to actually render in the unselected cluster.
  const visibleUnselected = expanded
    ? unselectedFiltered
    : unselectedFiltered.slice(0, TAG_PAGE_SIZE);

  const hasTags = facets.tags.length > 0;

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <FilterPanel title="Filters" defaultExpanded={defaultExpanded}>
      <Stack direction="vertical" gap={8}>
        {/* Correspondent filter — avoid passing undefined to value under
            exactOptionalPropertyTypes: use a conditional spread instead */}
        <Select
          id="filter-correspondent"
          label="Correspondent"
          options={correspondentOptions}
          {...(selectedCorrespondentValue !== undefined ? { value: selectedCorrespondentValue } : {})}
          placeholder="All correspondents"
          onChange={handleCorrespondentChange}
        />

        {/* Document type filter */}
        <Select
          id="filter-document-type"
          label="Document type"
          options={documentTypeOptions}
          {...(selectedDocumentTypeValue !== undefined ? { value: selectedDocumentTypeValue } : {})}
          placeholder="All types"
          onChange={handleDocumentTypeChange}
        />

        {/* Tag picker — bounded chip cluster with search and expand toggle. */}
        {hasTags && (
          <div className={styles['tag-section']}>
            <span className={styles['section-label']} id="filter-tags-label">
              Tags
            </span>

            {/* Search input — filters the unselected tag list by name. */}
            <Input
              id="filter-tags-search"
              label="Search tags"
              type="search"
              placeholder="Filter tags…"
              value={tagQuery}
              onChange={handleTagQueryChange}
              autoComplete="off"
            />

            {/* Chip cluster — selected pinned at top, then visible unselected. */}
            <div
              className={expanded ? styles['tag-list-scroll'] : undefined}
              role="group"
              aria-labelledby="filter-tags-label"
            >
              <div className={styles['tag-chips']}>
                {selectedTags.map((tag) => (
                  <Chip
                    key={tag.id}
                    selected
                    onClick={() => handleTagToggle(tag.id)}
                  >
                    {tag.name}
                  </Chip>
                ))}
                {visibleUnselected.map((tag) => (
                  <Chip
                    key={tag.id}
                    selected={false}
                    onClick={() => handleTagToggle(tag.id)}
                  >
                    {tag.name}
                  </Chip>
                ))}
              </div>
            </div>

            {/* Expand / collapse toggle — only shown when there are hidden
                tags. Ghost Button (FE-15) replaces the bespoke link button: it
                carries the token focus ring and consistent styling. The visible
                label ("Show all (N)" / "Show less") conveys the expanded state. */}
            {needsToggle && (
              <Button
                variant="ghost"
                size="small"
                onClick={() => setExpanded((prev) => !prev)}
              >
                {expanded
                  ? 'Show less'
                  : `Show all (${unselectedFiltered.length})`}
              </Button>
            )}
          </div>
        )}

        {/* Date range — functional inputs for date_from / date_to filters */}
        <Stack direction="vertical" gap={4}>
          <Input
            id="filter-date-from"
            label="From"
            type="date"
            value={filters.date_from ?? ''}
            onChange={handleDateFromChange}
          />
          <Input
            id="filter-date-to"
            label="To"
            type="date"
            value={filters.date_to ?? ''}
            onChange={handleDateToChange}
          />
        </Stack>
      </Stack>
    </FilterPanel>
  );
}
