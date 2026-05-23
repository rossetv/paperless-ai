import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import { RebuildIndexCard } from './RebuildIndexCard';

// --- Mock the rebuild mutation -------------------------------------------
vi.mock('../../../api/hooks', () => ({
  useRebuildIndex: vi.fn(),
}));

import { useRebuildIndex } from '../../../api/hooks';
const mockUseRebuildIndex = useRebuildIndex as ReturnType<typeof vi.fn>;

function makeMutation(
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

/**
 * Wait for the Modal's focus-trap requestAnimationFrame to settle by asserting
 * that focus has moved inside the dialog. Waiting only for `!== document.body`
 * is insufficient — the open button holds focus briefly after the click, before
 * the RAF fires and moves focus into the dialog. Typing before the RAF settles
 * causes characters to go to the wrong element.
 */
async function waitForModalFocus(): Promise<void> {
  await waitFor(() => {
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
  });
}

describe('RebuildIndexCard', () => {
  it('renders the danger-zone title', () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    expect(screen.getByText(/rebuild index from scratch/i)).toBeInTheDocument();
  });

  it('does not show the confirmation modal initially', () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens the confirmation modal when the rebuild button is clicked', async () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps the confirm button disabled until REBUILD is typed', async () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    const confirm = screen.getByRole('button', { name: /^rebuild now$/i });
    expect(confirm).toBeDisabled();
  });

  it('leaves the confirm button disabled for the wrong word', async () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await waitForModalFocus();
    await userEvent.type(screen.getByLabelText(/type rebuild to confirm/i), 'delete');
    expect(screen.getByRole('button', { name: /^rebuild now$/i })).toBeDisabled();
  });

  it('enables the confirm button once REBUILD is typed exactly', async () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await waitForModalFocus();
    await userEvent.type(screen.getByLabelText(/type rebuild to confirm/i), 'REBUILD');
    expect(screen.getByRole('button', { name: /^rebuild now$/i })).toBeEnabled();
  });

  it('calls the rebuild mutation when confirmed', async () => {
    const mutation = makeMutation();
    mockUseRebuildIndex.mockReturnValue(mutation);
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await waitForModalFocus();
    await userEvent.type(screen.getByLabelText(/type rebuild to confirm/i), 'REBUILD');
    await userEvent.click(screen.getByRole('button', { name: /^rebuild now$/i }));
    expect(mutation.mutateAsync).toHaveBeenCalledTimes(1);
  });

  it('does not call the mutation when the modal is cancelled', async () => {
    const mutation = makeMutation();
    mockUseRebuildIndex.mockReturnValue(mutation);
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    expect(mutation.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes the modal after a successful rebuild', async () => {
    const mutation = makeMutation();
    mockUseRebuildIndex.mockReturnValue(mutation);
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await waitForModalFocus();
    await userEvent.type(screen.getByLabelText(/type rebuild to confirm/i), 'REBUILD');
    await userEvent.click(screen.getByRole('button', { name: /^rebuild now$/i }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows an error message when the rebuild mutation fails', async () => {
    mockUseRebuildIndex.mockReturnValue(
      makeMutation({ isError: true, error: new Error('boom') }),
    );
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/could not start the rebuild/i);
  });

  it('disables the confirm button while the rebuild is pending', async () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation({ isPending: true }));
    render(<RebuildIndexCard />);
    await userEvent.click(screen.getByRole('button', { name: /rebuild index/i }));
    await waitForModalFocus();
    await userEvent.type(screen.getByLabelText(/type rebuild to confirm/i), 'REBUILD');
    expect(screen.getByRole('button', { name: /rebuilding/i })).toBeDisabled();
  });

  it('forwards a custom className onto the root card', () => {
    mockUseRebuildIndex.mockReturnValue(makeMutation());
    const { container } = render(<RebuildIndexCard className="extra" />);
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
