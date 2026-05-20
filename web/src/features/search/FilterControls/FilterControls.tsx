import React from 'react';
import { FilterPanel } from '../../../components/patterns/FilterPanel/FilterPanel';
import { Select } from '../../../components/patterns/Select/Select';
import type { SelectOption } from '../../../components/patterns/Select/Select';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Skeleton } from '../../../components/primitives/Skeleton/Skeleton';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Input } from '../../../components/primitives/Input/Input';
import { Stack } from '../../../components/layout/Stack/Stack';
import { useFacets } from '../../../api/hooks';
import type { FilterRequest, TaxonomyEntry } from '../../../api/types';

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
 * Composed from: FilterPanel, Select, Chip, Skeleton, Stack.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function FilterControls({
  filters,
  onFiltersChange,
}: FilterControlsProps): React.ReactElement {
  const { data: facets, isLoading, isError } = useFacets();

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

  if (isError) {
    return (
      <EmptyState
        icon="warning"
        message="Filters are unavailable"
        description="Could not load filter options. You can still search without filters."
      />
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

  return (
    <FilterPanel title="Filters">
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

        {/* Tag chips — click to toggle; selected chips use the accent state. */}
        {facets.tags.length > 0 && (
          <Stack direction="horizontal" gap={3} wrap>
            {facets.tags.map((tag) => (
              <Chip
                key={tag.id}
                selected={filters.tag_ids.includes(tag.id)}
                onClick={() => handleTagToggle(tag.id)}
              >
                {tag.name}
              </Chip>
            ))}
          </Stack>
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
