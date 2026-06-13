import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SaveBar } from './SaveBar';

function renderBar(props: Partial<Parameters<typeof SaveBar>[0]> = {}) {
  return render(
    <SaveBar
      dirtyCount={0}
      isPending={false}
      onDiscard={() => {}}
      onSave={() => {}}
      {...props}
    />,
  );
}

describe('SaveBar', () => {
  it('is visually hidden when dirtyCount is zero', () => {
    const { container } = renderBar({ dirtyCount: 0 });
    const bar = container.firstElementChild as HTMLElement;
    expect(bar.className).toMatch(/bar-hidden/);
    expect(bar).toHaveAttribute('inert', '');
  });

  it('is visible when dirtyCount is greater than zero', () => {
    const { container } = renderBar({ dirtyCount: 1 });
    const bar = container.firstElementChild as HTMLElement;
    expect(bar.className).not.toMatch(/bar-hidden/);
    expect(bar).not.toHaveAttribute('inert');
  });

  it('carries aria-live and aria-atomic for screen-reader announcements', () => {
    const { container } = renderBar({ dirtyCount: 1 });
    const bar = container.firstElementChild as HTMLElement;
    expect(bar).toHaveAttribute('aria-live', 'polite');
    expect(bar).toHaveAttribute('aria-atomic', 'true');
  });

  it('shows the unsaved change count', () => {
    renderBar({ dirtyCount: 3 });
    expect(screen.getByText(/3 unsaved changes/i)).toBeInTheDocument();
  });

  it('uses singular "change" when dirtyCount is 1', () => {
    renderBar({ dirtyCount: 1 });
    expect(screen.getByText(/1 unsaved change/i)).toBeInTheDocument();
  });

  it('renders a Discard button', () => {
    renderBar({ dirtyCount: 2 });
    expect(screen.getByRole('button', { name: /discard/i })).toBeInTheDocument();
  });

  it('renders a Save changes button', () => {
    renderBar({ dirtyCount: 2 });
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument();
  });

  it('disables both buttons while pending', () => {
    renderBar({ dirtyCount: 2, isPending: true });
    expect(screen.getByRole('button', { name: /discard/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });

  it('calls onDiscard when Discard is clicked', async () => {
    const onDiscard = vi.fn();
    renderBar({ dirtyCount: 2, onDiscard });
    await userEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it('calls onSave when Save is clicked', async () => {
    const onSave = vi.fn();
    renderBar({ dirtyCount: 2, onSave });
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it('shows the normal "no restart" caption when reindexPending is false', () => {
    renderBar({ dirtyCount: 1, reindexPending: false });
    expect(screen.getByText(/no restart/i)).toBeInTheDocument();
  });

  it('shows the normal "no restart" caption when reindexPending is absent', () => {
    renderBar({ dirtyCount: 1 });
    expect(screen.getByText(/no restart/i)).toBeInTheDocument();
  });

  it('shows the rebuild warning caption when reindexPending is true', () => {
    renderBar({ dirtyCount: 1, reindexPending: true });
    expect(screen.getByText(/rebuild|re-embed/i)).toBeInTheDocument();
  });

  it('rebuild warning caption does not contain "no restart" when reindexPending is true', () => {
    renderBar({ dirtyCount: 1, reindexPending: true });
    expect(screen.queryByText(/no restart/i)).toBeNull();
  });
});
