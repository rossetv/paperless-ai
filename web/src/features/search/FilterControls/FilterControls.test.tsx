import { render, screen } from '@testing-library/react';
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

const emptyFilters: FilterRequest = {
  tag_ids: [],
};

describe('FilterControls', () => {
  beforeEach(() => {
    mockUseFacets.mockReturnValue({ data: facets, isLoading: false, isError: false });
  });

  it('renders correspondent options from facets', async () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    // The select trigger for correspondent should be present
    expect(screen.getByRole('combobox', { name: /correspondent/i })).toBeInTheDocument();
  });

  it('renders document type options from facets', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: /document type/i })).toBeInTheDocument();
  });

  it('renders tag chips from facets', () => {
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    expect(screen.getByText('tax')).toBeInTheDocument();
    expect(screen.getByText('warranty')).toBeInTheDocument();
  });

  it('calls onFiltersChange with correspondent_id when a correspondent is selected', async () => {
    const handler = vi.fn();
    render(<FilterControls filters={emptyFilters} onFiltersChange={handler} />);

    // Open the correspondent combobox
    await userEvent.click(screen.getByRole('combobox', { name: /correspondent/i }));
    await userEvent.click(screen.getByRole('option', { name: 'HMRC' }));

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ correspondent_id: 1 }),
    );
  });

  it('calls onFiltersChange with updated tag_ids when a tag chip is clicked', async () => {
    const handler = vi.fn();
    render(<FilterControls filters={emptyFilters} onFiltersChange={handler} />);

    await userEvent.click(screen.getByText('tax'));
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ tag_ids: [100] }),
    );
  });

  it('shows a loading skeleton when facets are loading', () => {
    mockUseFacets.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<FilterControls filters={emptyFilters} onFiltersChange={vi.fn()} />);
    // Skeleton elements are aria-hidden; check the loading indicator is present
    // by confirming the selects are NOT rendered yet
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('reflects pre-selected correspondent in the combobox', () => {
    const preSelected: FilterRequest = { tag_ids: [], correspondent_id: 2 };
    render(<FilterControls filters={preSelected} onFiltersChange={vi.fn()} />);
    // The combobox trigger should show the selected correspondent name
    expect(screen.getByText('Vaillant')).toBeInTheDocument();
  });
});
