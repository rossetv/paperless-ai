import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IdleScreen } from './IdleScreen';

// Mock the API hooks so the feature renders without a QueryClient.
vi.mock('../../../api/hooks', () => ({
  useRecentSearches: vi.fn(),
  useStats: vi.fn(),
}));

import { useRecentSearches, useStats } from '../../../api/hooks';

const mockRecent = useRecentSearches as ReturnType<typeof vi.fn>;
const mockStats = useStats as ReturnType<typeof vi.fn>;

/** A minimal "successful query" stub for a react-query result. */
function ok<T>(data: T) {
  return { data, isSuccess: true, isLoading: false, isError: false, error: null };
}
/** A minimal "errored query" stub. */
function failed() {
  return {
    data: undefined,
    isSuccess: false,
    isLoading: false,
    isError: true,
    error: new Error('nope'),
  };
}

beforeEach(() => {
  mockRecent.mockReturnValue(
    ok({
      searches: [
        { query: 'npower 2024', searched_at: '2026-05-22T10:00:00Z' },
      ],
    }),
  );
  mockStats.mockReturnValue(
    ok({
      document_count: 14238,
      chunk_count: 187612,
      last_reconcile_at: '2026-05-22T11:00:00Z',
      embedding_model: 'text-embedding-3-small',
    }),
  );
});

describe('IdleScreen', () => {
  it('renders the hero headline', () => {
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.getByText(/ask your library/i)).toBeInTheDocument();
  });

  it('renders the large search field', () => {
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('runs a search when the user submits a query', async () => {
    const onSearch = vi.fn();
    render(<IdleScreen onSearch={onSearch} />);
    const box = screen.getByRole('searchbox');
    await userEvent.type(box, 'energy bills{Enter}');
    expect(onSearch).toHaveBeenCalledWith('energy bills');
  });

  it('runs a search when a quick-filter chip is clicked', async () => {
    const onSearch = vi.fn();
    render(<IdleScreen onSearch={onSearch} />);
    await userEvent.click(
      screen.getByRole('button', { name: 'Bank statements' }),
    );
    expect(onSearch).toHaveBeenCalledWith('Bank statements');
  });

  it('renders the recent searches', () => {
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.getByText('npower 2024')).toBeInTheDocument();
  });

  it('runs a search when a recent-search row is clicked', async () => {
    const onSearch = vi.fn();
    render(<IdleScreen onSearch={onSearch} />);
    await userEvent.click(screen.getByText('npower 2024'));
    expect(onSearch).toHaveBeenCalledWith('npower 2024');
  });

  it('omits the recent-searches strip when the query fails', () => {
    mockRecent.mockReturnValue(failed());
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.queryByText(/recent searches/i)).not.toBeInTheDocument();
  });

  it('renders the index-status footer counts', () => {
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.getByText(/14,238 documents/)).toBeInTheDocument();
  });

  it('omits the status footer while stats are loading', () => {
    mockStats.mockReturnValue({
      data: undefined,
      isSuccess: false,
      isLoading: true,
      isError: false,
      error: null,
    });
    render(<IdleScreen onSearch={() => {}} />);
    expect(screen.queryByText(/index ready/i)).not.toBeInTheDocument();
  });
});
