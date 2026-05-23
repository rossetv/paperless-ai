import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActiveFiltersStrip } from './ActiveFiltersStrip';

// useFacets drives name resolution — mock it for isolation.
vi.mock('../../../api/hooks', () => ({
  useFacets: vi.fn(),
}));

import { useFacets } from '../../../api/hooks';

const mockUseFacets = useFacets as ReturnType<typeof vi.fn>;

const FACETS = {
  correspondents: [{ kind: 'correspondent', id: 1, name: 'Npower Energy' }],
  document_types: [{ kind: 'document_type', id: 2, name: 'Statement' }],
  tags: [
    { kind: 'tag', id: 10, name: 'Banking' },
    { kind: 'tag', id: 11, name: 'Tax' },
  ],
  earliest: null,
  latest: null,
};

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

beforeEach(() => {
  mockUseFacets.mockReturnValue({ data: FACETS });
});

describe('ActiveFiltersStrip', () => {
  it('renders nothing when no filters are active', () => {
    const { container } = render(
      <ActiveFiltersStrip
        filters={EMPTY_FILTERS}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders "Filtered by" when a tag filter is active', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, tag_ids: [10] }}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('Filtered by')).toBeInTheDocument();
  });

  it('renders a chip for each active tag', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, tag_ids: [10, 11] }}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('Tax')).toBeInTheDocument();
  });

  it('renders a chip for active correspondent', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, correspondent_id: 1 }}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
  });

  it('renders a chip for active document type', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, document_type_id: 2 }}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('Statement')).toBeInTheDocument();
  });

  it('renders the document count', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, tag_ids: [10] }}
        docCount={4}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('4 documents')).toBeInTheDocument();
  });

  it('renders "1 document" (singular) when docCount is 1', () => {
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, tag_ids: [10] }}
        docCount={1}
        onClearAll={() => {}}
      />,
    );
    expect(screen.getByText('1 document')).toBeInTheDocument();
  });

  it('fires onClearAll when "Clear all" is clicked', async () => {
    const onClearAll = vi.fn();
    render(
      <ActiveFiltersStrip
        filters={{ ...EMPTY_FILTERS, tag_ids: [10] }}
        docCount={4}
        onClearAll={onClearAll}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });
});
