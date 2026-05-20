import React from 'react';
import { FilterPanel } from '../../../components/patterns/FilterPanel/FilterPanel';
import { Select } from '../../../components/patterns/Select/Select';
import type { SelectOption } from '../../../components/patterns/Select/Select';
import { Button } from '../../../components/primitives/Button/Button';
import { Skeleton } from '../../../components/primitives/Skeleton/Skeleton';
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
  const { data: facets, isLoading } = useFacets();

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

  if (isLoading || facets === undefined) {
    return (
      <Stack direction="vertical" gap={6}>
        <Skeleton variant="rectangular" height="40px" />
        <Skeleton variant="rectangular" height="40px" />
        <Skeleton variant="rectangular" height="32px" />
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
        {/* Correspondent filter */}
        <Select
          id="filter-correspondent"
          label="Correspondent"
          options={correspondentOptions}
          value={selectedCorrespondentValue}
          placeholder="All correspondents"
          onChange={handleCorrespondentChange}
        />

        {/* Document type filter */}
        <Select
          id="filter-document-type"
          label="Document type"
          options={documentTypeOptions}
          value={selectedDocumentTypeValue}
          placeholder="All types"
          onChange={handleDocumentTypeChange}
        />

        {/* Tag toggle buttons — each tag is a toggle; selected tags use the
            primary variant to signal active state, unselected use secondary. */}
        {facets.tags.length > 0 && (
          <Stack direction="horizontal" gap={3} wrap>
            {facets.tags.map((tag) => (
              <Button
                key={tag.id}
                variant={filters.tag_ids.includes(tag.id) ? 'primary' : 'secondary'}
                size="small"
                onClick={() => handleTagToggle(tag.id)}
              >
                {tag.name}
              </Button>
            ))}
          </Stack>
        )}

        {/* Date range — rendered as plain inputs when earliest/latest are known */}
        {(facets.earliest !== null || facets.latest !== null) && (
          <Stack direction="horizontal" gap={4}>
            {facets.earliest !== null && (
              <span>From: {facets.earliest}</span>
            )}
            {facets.latest !== null && (
              <span>To: {facets.latest}</span>
            )}
          </Stack>
        )}
      </Stack>
    </FilterPanel>
  );
}
