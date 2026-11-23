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
import { isNarrowViewport } from '../../../lib/isNarrowViewport';
import type { FilterRequest, TaxonomyEntry } from '../../../api/types';
import styles from './FilterControls.module.css';

/** Maximum number of unselected tags to show before the "Show all" toggle. */
const TAG_PAGE_SIZE = 12;

/** Debounce delay (ms) for the tag search input. */
const TAG_SEARCH_DEBOUNCE_MS = 200;

export interface FilterControlsProps {
  /** The active filters, controlled by the parent. */
  filters: FilterRequest;
  /** Called with the updated filters whenever the user changes one. */
  onFiltersChange: (filters: FilterRequest) => void;
  /**
   * Whether the "Filters" panel starts expanded. Defaults to true, except on a
   * narrow viewport, where the rail stacks above the content and would push it
   * below the fold.
   */
  defaultExpanded?: boolean;
}

function toOptions(entries: TaxonomyEntry[]): SelectOption<string>[] {
  return entries.map((e) => ({ value: String(e.id), label: e.name }));
}

/**
 * Filter panel for correspondent, document type, tags and date range. Options
 * come from useFacets, so only values present in the index are offered.
 *
 * Selected tags are pinned at the top, followed by up to TAG_PAGE_SIZE unselected
 * tags; "Show all (N)" expands the rest into a capped scroll region, and a
 * debounced input filters the list by name.
 */
export function FilterControls({
  filters,
  onFiltersChange,
  defaultExpanded,
}: FilterControlsProps): React.ReactElement {
  const { data: facets, isLoading, isError } = useFacets();

  // Tag search input — raw (undebounced) value drives the visible input.
  const [tagQuery, setTagQuery] = React.useState('');
  const debouncedQuery = useDebounce(tagQuery, TAG_SEARCH_DEBOUNCE_MS);
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

  const allTagsSorted = [...facets.tags].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  // Tags the user has selected (always pinned at top, regardless of filter).
  const selectedTags = allTagsSorted.filter((t) => filters.tag_ids.includes(t.id));

  const query = debouncedQuery.trim().toLowerCase();
  const unselectedFiltered = allTagsSorted.filter(
    (t) =>
      !filters.tag_ids.includes(t.id) &&
      (query === '' || t.name.toLowerCase().includes(query)),
  );

  const hiddenCount = Math.max(0, unselectedFiltered.length - TAG_PAGE_SIZE);
  const needsToggle = hiddenCount > 0;

  const visibleUnselected = expanded
    ? unselectedFiltered
    : unselectedFiltered.slice(0, TAG_PAGE_SIZE);

  const hasTags = facets.tags.length > 0;

  return (
    <FilterPanel title="Filters" defaultExpanded={defaultExpanded ?? !isNarrowViewport()}>
      <Stack direction="vertical" gap={8}>
        {/* Conditional spread: exactOptionalPropertyTypes forbids passing undefined to value. */}
        <Select
          id="filter-correspondent"
          label="Correspondent"
          options={correspondentOptions}
          {...(selectedCorrespondentValue !== undefined ? { value: selectedCorrespondentValue } : {})}
          placeholder="All correspondents"
          onChange={handleCorrespondentChange}
        />

        <Select
          id="filter-document-type"
          label="Document type"
          options={documentTypeOptions}
          {...(selectedDocumentTypeValue !== undefined ? { value: selectedDocumentTypeValue } : {})}
          placeholder="All types"
          onChange={handleDocumentTypeChange}
        />

        {hasTags && (
          <div className={styles['tag-section']}>
            <span className={styles['section-label']} id="filter-tags-label">
              Tags
            </span>

            <Input
              id="filter-tags-search"
              label="Search tags"
              type="search"
              placeholder="Filter tags…"
              value={tagQuery}
              onChange={handleTagQueryChange}
              autoComplete="off"
            />

            {/* Selected tags pinned first, then the visible unselected ones. */}
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

            {/* The label ("Show all (N)" / "Show less") conveys the expanded state. */}
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
