import { hasActiveFilters } from './filters';
import type { FilterRequest } from '../../api/types';

const EMPTY: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

describe('hasActiveFilters', () => {
  it('returns false when all filters are empty', () => {
    expect(hasActiveFilters(EMPTY)).toBe(false);
  });

  it('returns true when tag_ids is non-empty', () => {
    expect(hasActiveFilters({ ...EMPTY, tag_ids: [1] })).toBe(true);
  });

  it('returns true when correspondent_id is set', () => {
    expect(hasActiveFilters({ ...EMPTY, correspondent_id: 42 })).toBe(true);
  });

  it('returns true when document_type_id is set', () => {
    expect(hasActiveFilters({ ...EMPTY, document_type_id: 7 })).toBe(true);
  });

  it('returns true when date_from is set', () => {
    expect(hasActiveFilters({ ...EMPTY, date_from: '2024-01-01' })).toBe(true);
  });

  it('returns true when date_to is set', () => {
    expect(hasActiveFilters({ ...EMPTY, date_to: '2024-12-31' })).toBe(true);
  });

  it('returns true when multiple filters are set', () => {
    expect(
      hasActiveFilters({
        tag_ids: [1, 2],
        correspondent_id: 5,
        document_type_id: null,
        date_from: '2023-01-01',
        date_to: null,
      }),
    ).toBe(true);
  });
});
