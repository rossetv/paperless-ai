import type { FilterRequest } from '../../api/types';

/** True when at least one filter value is set on the request. */
export function hasActiveFilters(filters: FilterRequest): boolean {
  return (
    filters.tag_ids.length > 0 ||
    filters.correspondent_id != null ||
    filters.document_type_id != null ||
    filters.date_from != null ||
    filters.date_to != null
  );
}
