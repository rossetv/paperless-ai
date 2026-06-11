/**
 * Shared filter helpers for the search feature.
 *
 * Extracted from `ActiveFiltersStrip` so any component that needs to
 * branch on whether the user has set at least one filter can import
 * `hasActiveFilters` without pulling in the full strip component.
 *
 * Allowed deps: API types only (leaf module — CODE_GUIDELINES §12.3).
 */

import type { FilterRequest } from '../../api/types';

/**
 * Returns true when at least one filter value is set on the given request.
 *
 * A filter is "set" when:
 * - `tag_ids` is non-empty, OR
 * - `correspondent_id` is not null/undefined, OR
 * - `document_type_id` is not null/undefined, OR
 * - `date_from` is not null/undefined, OR
 * - `date_to` is not null/undefined.
 */
export function hasActiveFilters(filters: FilterRequest): boolean {
  return (
    filters.tag_ids.length > 0 ||
    filters.correspondent_id != null ||
    filters.document_type_id != null ||
    filters.date_from != null ||
    filters.date_to != null
  );
}
