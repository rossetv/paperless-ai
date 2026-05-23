import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { FacetsResponse, FilterRequest } from '../../../api/types';
import { FilterControls } from './FilterControls';

// ---------------------------------------------------------------------------
// Mock the useFacets hook so tests do not need a real QueryClient or network
// ---------------------------------------------------------------------------
vi.mock('../../../api/hooks', () => ({
  useFacets: vi.fn(),
}));

import { useFacets } from '../../../api/hooks';
const mockUseFacets = useFacets as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Two tags — well under the 12-chip threshold. */
const facets: FacetsResponse = {
  correspondents: [
    { kind: 'correspondent', id: 1, name: 'HMRC' },
    { kind: 'correspondent', id: 2, name: 'Vaillant' },
  ],
  document_types: [
    { kind: 'document_type', id: 10, name: 'Invoice' },
    { kind: 'document_type', id: 11, name: 'Letter' },
  ],
  tags: [
    { kind: 'tag', id: 100, name: 'tax' },
    { kind: 'tag', id: 101, name: 'warranty' },
  ],
  earliest: '2020-01-01',
  latest: '2024-12-31',
};

/**
 * Build facets with N tags (names: tag-1, tag-2, …, tag-N).
 * Handy for testing the bounded / "Show all" path.
 */
function makeFacetsWithTags(n: number): FacetsResponse {
  return {
    ...facets,
    tags: Array.from({ length: n }, (_, i) => ({
      kind: 'tag' as const,
      id: 200 + i,
      name: `tag-${i + 1}`,
    })),
  };
}

const emptyFilters: FilterRequest = {
  tag_ids: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FilterControls', () => {
  beforeEach(() => {
    mockUseFacets.mockReturnValue({ data: facets, isLoading: false, isError: false });
  });

  // ── Existing smoke tests (preserved) ──────────────────────────────────────

  it('renders correspondent options from facets', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: /correspondent/i })).toBeInTheDocument();
  });

  it('renders document type options from facets', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: /document type/i })).toBeInTheDocument();
  });

  it('renders tag chips from facets', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'tax' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'warranty' })).toBeInTheDocument();
  });

  it('calls onFiltersChange with correspondent_id when a correspondent is selected', async () => {
    const handler = vi.fn();
    render(<FilterControls filters={emptyFilters} onFiltersChange={handler} />);

    await userEvent.click(screen.getByRole('combobox', { name: /correspondent/i }));
    await userEvent.click(screen.getByRole('option', { name: 'HMRC' }));

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ correspondent_id: 1 }),
    );
  });

  it('calls onFiltersChange with updated tag_ids when a tag chip is clicked', async () => {
    const handler = vi.fn();
    render(<FilterControls filters={emptyFilters} onFiltersChange={handler} />);

    await userEvent.click(screen.getByRole('button', { name: 'tax' }));
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ tag_ids: [100] }),
    );
  });

  it('calls onFiltersChange with date_from when the From date input changes', async () => {
    const handler = vi.fn();
    render(<FilterControls filters={emptyFilters} onFiltersChange={handler} />);

    const fromInput = screen.getByLabelText(/^from$/i);
    await userEvent.type(fromInput, '2023-01-01');
    expect(handler).toHaveBeenLastCalledWith(
      expect.objectContaining({ date_from: expect.stringContaining('2023') }),
    );
  });

  it('shows a loading skeleton when facets are loading', () => {
    mockUseFacets.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('shows degraded state instead of skeletons on facets fetch error', () => {
    mockUseFacets.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByText(/filters are unavailable/i)).toBeInTheDocument();
  });

  it('reflects pre-selected correspondent in the combobox', () => {
    const preSelected: FilterRequest = { tag_ids: [], correspondent_id: 2 };
    render(<FilterControls filters={preSelected} onFiltersChange={vi.fn()} />);
    expect(screen.getByText('Vaillant')).toBeInTheDocument();
  });

  // ── Bounded tag picker — ≤ 12 tags ──────────────────────────────────────

  it('shows all tags when total is within the 12-chip limit', () => {
    // facets fixture has 2 tags — both should be visible.
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    const group = screen.getByRole('group', { name: /tags/i });
    expect(within(group).getByRole('button', { name: 'tax' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'warranty' })).toBeInTheDocument();
    // No "Show all" toggle should appear.
    expect(screen.queryByRole('button', { name: /show all/i })).not.toBeInTheDocument();
  });

  it('shows exactly 12 unselected chips when there are more than 12 tags', () => {
    mockUseFacets.mockReturnValue({
      data: makeFacetsWithTags(20),
      isLoading: false,
      isError: false,
    });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);

    // Should show exactly 12 tag chips (all unselected, none selected).
    const group = screen.getByRole('group', { name: /tags/i });
    const chips = within(group).getAllByRole('button');
    expect(chips).toHaveLength(12);
  });

  // ── "Show all" toggle ────────────────────────────────────────────────────

  it('renders the "Show all" button when more than 12 unselected tags exist', () => {
    mockUseFacets.mockReturnValue({
      data: makeFacetsWithTags(15),
      isLoading: false,
      isError: false,
    });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);

    const toggle = screen.getByRole('button', { name: /show all \(15\)/i });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands to show all tags when "Show all" is clicked', async () => {
    mockUseFacets.mockReturnValue({
      data: makeFacetsWithTags(15),
      isLoading: false,
      isError: false,
    });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);

    const toggle = screen.getByRole('button', { name: /show all/i });
    await userEvent.click(toggle);

    // All 15 tag chips should now be in the group.
    const group = screen.getByRole('group', { name: /tags/i });
    const chips = within(group).getAllByRole('button');
    expect(chips).toHaveLength(15);

    // The button label should change and aria-expanded should be true.
    const collapseButton = screen.getByRole('button', { name: /show less/i });
    expect(collapseButton).toHaveAttribute('aria-expanded', 'true');
  });

  it('collapses back to 12 when "Show less" is clicked', async () => {
    mockUseFacets.mockReturnValue({
      data: makeFacetsWithTags(15),
      isLoading: false,
      isError: false,
    });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /show all/i }));
    await userEvent.click(screen.getByRole('button', { name: /show less/i }));

    const group = screen.getByRole('group', { name: /tags/i });
    const chips = within(group).getAllByRole('button');
    expect(chips).toHaveLength(12);
  });

  // ── Tag search input ─────────────────────────────────────────────────────

  it('renders the tag search input with an accessible label', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('searchbox', { name: /search tags/i })).toBeInTheDocument();
  });

  it('narrows visible unselected chips as the user types in the search input', async () => {
    // Use the default facets (tax, warranty).
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);

    const searchInput = screen.getByRole('searchbox', { name: /search tags/i });
    await userEvent.type(searchInput, 'war');

    // After debounce — wait for the filtered result to appear.
    await waitFor(() => {
      const group = screen.getByRole('group', { name: /tags/i });
      expect(within(group).queryByRole('button', { name: 'tax' })).not.toBeInTheDocument();
      expect(within(group).getByRole('button', { name: 'warranty' })).toBeInTheDocument();
    });
  });

  it('keeps selected tags visible even when the search query does not match them', async () => {
    // Start with 'tax' pre-selected.
    const preSelected: FilterRequest = { tag_ids: [100] };
    render(<FilterControls filters={preSelected} onFiltersChange={vi.fn()} />);

    const searchInput = screen.getByRole('searchbox', { name: /search tags/i });
    await userEvent.type(searchInput, 'war');

    await waitFor(() => {
      const group = screen.getByRole('group', { name: /tags/i });
      // 'tax' is selected — must stay pinned at top.
      expect(within(group).getByRole('button', { name: 'tax' })).toBeInTheDocument();
      // 'warranty' matches the query.
      expect(within(group).getByRole('button', { name: 'warranty' })).toBeInTheDocument();
    });
  });

  // ── Tag toggle correctness with mixed state ───────────────────────────────

  it('deselects a tag when a selected chip is clicked', async () => {
    const handler = vi.fn();
    const preSelected: FilterRequest = { tag_ids: [100, 101] };
    render(<FilterControls filters={preSelected} onFiltersChange={handler} />);

    await userEvent.click(screen.getByRole('button', { name: 'tax' }));
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ tag_ids: [101] }),
    );
  });

  it('adds a tag when an unselected chip is clicked', async () => {
    const handler = vi.fn();
    const preSelected: FilterRequest = { tag_ids: [100] };
    render(<FilterControls filters={preSelected} onFiltersChange={handler} />);

    await userEvent.click(screen.getByRole('button', { name: 'warranty' }));
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ tag_ids: [100, 101] }),
    );
  });

  // ── Accessibility ────────────────────────────────────────────────────────

  it('tag group has an accessible name via aria-labelledby', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: /tags/i })).toBeInTheDocument();
  });
});
