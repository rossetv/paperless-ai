import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { IndexScreen } from './IndexScreen';
import type {
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  StatsResponse,
  RebuildResponse,
} from '../../../api/types';

// --- Mocks ---------------------------------------------------------------
vi.mock('../../../api/hooks', () => ({
  useIndexStatus: vi.fn(),
  useIndexActivity: vi.fn(),
  useFailedDocuments: vi.fn(),
  useStats: vi.fn(),
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
  useStats,
  useReconcile,
  useRebuildIndex,
} from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';

const mockStatus = useIndexStatus as ReturnType<typeof vi.fn>;
const mockActivity = useIndexActivity as ReturnType<typeof vi.fn>;
const mockFailed = useFailedDocuments as ReturnType<typeof vi.fn>;
const mockStats = useStats as ReturnType<typeof vi.fn>;
const mockReconcile = useReconcile as ReturnType<typeof vi.fn>;
const mockRebuild = useRebuildIndex as ReturnType<typeof vi.fn>;
const mockAuth = useAuth as ReturnType<typeof vi.fn>;

// --- Fixtures — match wire.py exactly ------------------------------------

/**
 * Matches `IndexStatusResponse` from `wire.py`:
 *   health: str ("ok" | "degraded" | "down")
 *   daemons: list[DaemonStatusResponse]  (name, state, detail, processed_count, last_heartbeat)
 */
const STATUS: IndexStatusResponse = {
  health: 'ok',
  daemons: [
    { name: 'ocr', state: 'running', detail: '3 in flight', processed_count: 412, last_heartbeat: '2026-05-22T08:59:50Z' },
    { name: 'classifier', state: 'running', detail: '1 in flight', processed_count: 62, last_heartbeat: '2026-05-22T08:59:48Z' },
    { name: 'indexer', state: 'idle', detail: 'idle', processed_count: 14238, last_heartbeat: '2026-05-22T08:58:00Z' },
    { name: 'search', state: 'running', detail: 'serving', processed_count: 0, last_heartbeat: '2026-05-22T08:59:55Z' },
  ],
};

/**
 * Matches `IndexActivityResponse` from `wire.py`:
 *   cycles: list[ReconcileCycleResponse]  (id, kind, started_at, finished_at, ok, summary, detail)
 */
const ACTIVITY: IndexActivityResponse = {
  cycles: [
    {
      id: 1,
      kind: 'sync',
      started_at: '2026-05-22T08:56:00Z',
      finished_at: '2026-05-22T08:56:02Z',
      ok: true,
      summary: { indexed: 12, failed: 0 },
      detail: 'incremental sync complete',
    },
  ],
};

/**
 * Matches `IndexFailedResponse` from `wire.py`:
 *   documents: list[FailedDocumentResponse]  (document_id, title: str|None, failure_count)
 */
const FAILED: IndexFailedResponse = {
  documents: [
    {
      document_id: 8421,
      title: 'Scanned receipt #2891',
      failure_count: 3,
    },
  ],
};

/** Matches `StatsResponse` — from GET /api/stats, not GET /api/index/status. */
const STATS: StatsResponse = {
  document_count: 14238,
  chunk_count: 187612,
  last_reconcile_at: '2026-05-22T08:56:00Z',
  embedding_model: 'text-embedding-3-small',
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

function mutationResult<TData = void, TVariables = void>(
  overrides: Partial<UseMutationResult<TData, Error, TVariables>> = {},
): UseMutationResult<TData, Error, TVariables> {
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
  } as UseMutationResult<TData, Error, TVariables>;
}

/** Wire every mock to a happy, loaded, admin state. */
function primeAll(role: 'admin' | 'member' | 'readonly' = 'admin'): void {
  mockStatus.mockReturnValue(queryResult({ data: STATUS, isSuccess: true, status: 'success' }));
  mockActivity.mockReturnValue(queryResult({ data: ACTIVITY, isSuccess: true, status: 'success' }));
  mockFailed.mockReturnValue(queryResult({ data: FAILED, isSuccess: true, status: 'success' }));
  mockStats.mockReturnValue(queryResult({ data: STATS, isSuccess: true, status: 'success' }));
  mockReconcile.mockReturnValue(mutationResult());
  mockRebuild.mockReturnValue(mutationResult<RebuildResponse>());
  mockAuth.mockReturnValue({ user: { role }, role, isAuthenticated: true, isLoading: false });
}

describe('IndexScreen', () => {
  it('renders the page heading', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByRole('heading', { name: 'Index', level: 1 })).toBeInTheDocument();
  });

  it('renders the health hero (ok verdict maps to a healthy headline)', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText(/healthy/i)).toBeInTheDocument();
  });

  it('renders the stat tiles from the stats query (not the status query)', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('14,238')).toBeInTheDocument();
    expect(screen.getByText('187,612')).toBeInTheDocument();
    expect(screen.getByText('text-embedding-3-small')).toBeInTheDocument();
  });

  it('renders a card for every daemon using the real name field', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText('ocr')).toBeInTheDocument();
    expect(screen.getByText('classifier')).toBeInTheDocument();
    expect(screen.getByText('indexer')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
  });

  it('renders the recent-activity list from cycles (not entries)', () => {
    primeAll();
    render(<IndexScreen />);
    expect(screen.getByText(/incremental sync complete/)).toBeInTheDocument();
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

  it('hides "Reconcile now" for a read-only caller (backend rejects with 403)', () => {
    primeAll('readonly');
    render(<IndexScreen />);
    expect(screen.queryByRole('button', { name: /reconcile now/i })).not.toBeInTheDocument();
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
