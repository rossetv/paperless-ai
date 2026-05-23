import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { IndexScreen } from './IndexScreen';
import type {
  IndexStatusResponse,
  ActivityResponse,
  FailedResponse,
} from '../../../api/types';

// --- Mocks ---------------------------------------------------------------
vi.mock('../../../api/hooks', () => ({
  useIndexStatus: vi.fn(),
  useIndexActivity: vi.fn(),
  useFailedDocuments: vi.fn(),
  useRetryFailedDocument: vi.fn(),
  useReconcile: vi.fn(),
  useRebuildIndex: vi.fn(),
}));
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: vi.fn(),
}));

import {
  useIndexStatus,
  useIndexActivity,
  useFailedDocuments,
  useRetryFailedDocument,
  useReconcile,
  useRebuildIndex,
} from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';

const mockStatus = useIndexStatus as ReturnType<typeof vi.fn>;
const mockActivity = useIndexActivity as ReturnType<typeof vi.fn>;
const mockFailed = useFailedDocuments as ReturnType<typeof vi.fn>;
const mockRetry = useRetryFailedDocument as ReturnType<typeof vi.fn>;
const mockReconcile = useReconcile as ReturnType<typeof vi.fn>;
const mockRebuild = useRebuildIndex as ReturnType<typeof vi.fn>;
const mockAuth = useAuth as ReturnType<typeof vi.fn>;

// --- Fixtures ------------------------------------------------------------
const STATUS: IndexStatusResponse = {
  health: {
    healthy: true,
    headline: 'Healthy · ready to serve',
    detail: 'Schema present · integrity check passed.',
    uptime: '14d 6h',
    since: '2026-05-07T00:00:00Z',
  },
  daemons: [
    { key: 'ocr', name: 'OCR', role: 'Vision-model transcription', state: 'running', detail: '3 in flight', throughput: '412 pages / hr' },
    { key: 'classifier', name: 'Classifier', role: 'Metadata', state: 'running', detail: '1 in flight', throughput: '62 docs / hr' },
    { key: 'indexer', name: 'Indexer', role: 'Reconcile', state: 'idle', detail: 'Next cycle in 4m', throughput: 'incremental' },
    { key: 'search', name: 'Search', role: 'HTTP + MCP', state: 'running', detail: '0 in flight', throughput: '0 RPS' },
  ],
  document_count: 14238,
  chunk_count: 187612,
  embedding_model: 'text-embedding-3-small',
  index_size_bytes: 882900992,
};
const ACTIVITY: ActivityResponse = {
  entries: [
    { id: 'r1', status: 'ok', label: 'Reconcile cycle complete', detail: '+12 new', at: '2026-05-22T08:56:00Z' },
  ],
};
const FAILED: FailedResponse = {
  documents: [
    {
      document_id: 8421,
      title: 'Scanned receipt #2891',
      reason: 'OCR refused',
      failed_at: '2026-05-22T08:48:00Z',
    },
  ],
};

function queryResult<T>(
  overrides: Partial<UseQueryResult<T, Error>>,
): UseQueryResult<T, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isPending: false,
    isError: false,
    isSuccess: false,
    isFetching: false,
    status: 'pending',
    refetch: vi.fn(),
    ...overrides,
  } as UseQueryResult<T, Error>;
}

function mutationResult(
  overrides: Partial<UseMutationResult<void, Error, void>> = {},
): UseMutationResult<void, Error, void> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: 'idle',
    reset: vi.fn(),
    context: undefined,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
    variables: undefined,
    ...overrides,
  } as UseMutationResult<void, Error, void>;
}

/** Wire every mock to a happy, loaded, admin state. */
function primeAll(role: 'admin' | 'member' | 'readonly' = 'admin'): void {
  mockStatus.mockReturnValue(queryResult({ data: STATUS, isSuccess: true, status: 'success' }));
  mockActivity.mockReturnValue(queryResult({ data: ACTIVITY, isSuccess: true, status: 'success' }));
  mockFailed.mockReturnValue(queryResult({ data: FAILED, isSuccess: true, status: 'success' }));
  mockRetry.mockReturnValue(mutationResult() as unknown as ReturnType<typeof useRetryFailedDocument>);
  mockReconcile.mockReturnValue(mutationResult());
  mockRebuild.mockReturnValue(mutationResult());
  mockAuth.mockReturnValue({ user: { role }, role, isAuthenticated: true, isLoading: false });
}

describe('IndexScreen', () => {
  it('renders the page heading', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByRole('heading', { name: 'Index', level: 1 })).toBeInTheDocument();
  });

  it('renders the health hero headline from the status payload', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('Healthy · ready to serve')).toBeInTheDocument();
  });

  it('renders the stat tiles', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('14,238')).toBeInTheDocument();
    expect(screen.getByText('187,612')).toBeInTheDocument();
    expect(screen.getByText('text-embedding-3-small')).toBeInTheDocument();
  });

  it('renders a card for every daemon', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('OCR')).toBeInTheDocument();
    expect(screen.getByText('Classifier')).toBeInTheDocument();
    expect(screen.getByText('Indexer')).toBeInTheDocument();
    expect(screen.getByText('Search')).toBeInTheDocument();
  });

  it('renders the recent-activity list', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('Reconcile cycle complete')).toBeInTheDocument();
  });

  it('renders the failed-documents panel', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('Failed documents')).toBeInTheDocument();
    expect(screen.getByText('Scanned receipt #2891')).toBeInTheDocument();
  });

  it('shows a loading state while the status query is pending', () => {
    primeAll();
    mockStatus.mockReturnValue(queryResult({ isLoading: true, isPending: true }));
    render(<IndexScreen />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an error state when the status query fails', () => {
    primeAll();
    mockStatus.mockReturnValue(
      queryResult({ isError: true, error: new Error('boom'), status: 'error' }),
    );
    render(<IndexScreen />);
    expect(screen.getByRole('alert')).toHaveTextContent(/could not load the index status/i);
  });

  it('triggers a reconcile when "Reconcile now" is clicked', async () => {
    primeAll();
    const reconcile = mutationResult();
    mockReconcile.mockReturnValue(reconcile);
    render(<IndexScreen />);
    await userEvent.click(screen.getByRole('button', { name: /reconcile now/i }));
    expect(reconcile.mutate).toHaveBeenCalledTimes(1);
  });

  it('disables "Reconcile now" while a reconcile is pending', () => {
    primeAll();
    mockReconcile.mockReturnValue(mutationResult({ isPending: true }));
    render(<IndexScreen />);
    expect(screen.getByRole('button', { name: /reconciling/i })).toBeDisabled();
  });

  it('retries a failed document via the retry mutation', async () => {
    primeAll();
    const retry = mutationResult();
    mockRetry.mockReturnValue(retry as unknown as ReturnType<typeof useRetryFailedDocument>);
    render(<IndexScreen />);
    await userEvent.click(screen.getByRole('button', { name: /^retry$/i }));
    expect(retry.mutate).toHaveBeenCalledWith(8421);
  });

  it('shows the rebuild danger-zone card for an admin', () => {
    primeAll('admin');
    render(<IndexScreen />);
    expect(screen.getByText(/rebuild index from scratch/i)).toBeInTheDocument();
  });

  it('hides the rebuild danger-zone card for a non-admin', () => {
    primeAll('member');
    render(<IndexScreen />);
    expect(screen.queryByText(/rebuild index from scratch/i)).not.toBeInTheDocument();
  });
});
