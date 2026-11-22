import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { ApiError } from '../../../api/client';
import { ActionsCard } from './ActionsCard';

const noop = (): void => {};
const noopDelete = (): Promise<void> => Promise.resolve();

describe('ActionsCard', () => {
  it('renders Re-classify + Re-transcribe for a member; no Delete', () => {
    render(
      <ActionsCard
        documentId={42}
        role="member"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={noopDelete}
      />,
    );
    expect(screen.getByRole('button', { name: /re-classify/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /re-transcribe/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete/i })).not.toBeInTheDocument();
  });

  it('adds Delete for an admin', () => {
    render(
      <ActionsCard
        documentId={42}
        role="admin"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={noopDelete}
      />,
    );
    expect(screen.getByRole('button', { name: /^delete/i })).toBeInTheDocument();
  });

  it('renders nothing for readonly', () => {
    const { container } = render(
      <ActionsCard
        documentId={42}
        role="readonly"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={noopDelete}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('clicking Re-classify calls the handler with the document id', () => {
    const onReclassify = vi.fn();
    render(
      <ActionsCard
        documentId={42}
        role="member"
        title="Doc"
        onReclassify={onReclassify}
        onRetranscribe={noop}
        onDelete={noopDelete}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /re-classify/i }));
    expect(onReclassify).toHaveBeenCalledWith(42);
  });

  it('Delete opens a confirm modal; cancelling closes without firing onDelete', async () => {
    const onDelete = vi.fn(noopDelete);
    render(
      <ActionsCard
        documentId={42}
        role="admin"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={onDelete}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('Delete → Confirm fires onDelete with the document id', async () => {
    const onDelete = vi.fn(noopDelete);
    render(
      <ActionsCard
        documentId={42}
        role="admin"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={onDelete}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    const confirmBtn = await screen.findByRole('button', { name: /^delete$/i });
    fireEvent.click(confirmBtn);
    expect(onDelete).toHaveBeenCalledWith(42);
  });
  it('disables each action button while its request runs', () => {
    render(
      <ActionsCard
        documentId={42}
        role="admin"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={noopDelete}
        reclassifying
        retranscribing
        deleting
      />,
    );
    expect(screen.getByRole('button', { name: /re-classify/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /re-transcribe/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^delete document/i })).toBeDisabled();
  });

  it('keeps the confirm dialog open while the delete runs and closes it when it ends', async () => {
    let finish!: () => void;
    const onDelete = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const props = { documentId: 42, role: 'admin' as const, title: 'Doc', onReclassify: noop, onRetranscribe: noop, onDelete };
    const { rerender } = render(<ActionsCard {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    rerender(<ActionsCard {...props} deleting />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // A second confirm while the first is running sends nothing more.
    fireEvent.click(screen.getByRole('button', { name: /^deleting/i }));
    expect(onDelete).toHaveBeenCalledTimes(1);

    rerender(<ActionsCard {...props} deleting={false} />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    finish();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('a failed delete keeps the dialog open and shows the error inside it', async () => {
    const onDelete = vi.fn(() => Promise.reject(new ApiError(403, undefined, 'Admins only')));
    render(
      <ActionsCard documentId={42} role="admin" title="Doc" onReclassify={noop} onRetranscribe={noop} onDelete={onDelete} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('Admins only');
  });
});
