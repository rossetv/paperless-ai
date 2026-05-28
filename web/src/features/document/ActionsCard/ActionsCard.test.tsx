import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ActionsCard } from './ActionsCard';

const noop = (): void => {};

describe('ActionsCard', () => {
  it('renders Re-classify + Re-transcribe for a member; no Delete', () => {
    render(
      <ActionsCard
        documentId={42}
        role="member"
        title="Doc"
        onReclassify={noop}
        onRetranscribe={noop}
        onDelete={noop}
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
        onDelete={noop}
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
        onDelete={noop}
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
        onDelete={noop}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /re-classify/i }));
    expect(onReclassify).toHaveBeenCalledWith(42);
  });

  it('Delete opens a confirm modal; cancelling closes without firing onDelete', async () => {
    const onDelete = vi.fn();
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
    const onDelete = vi.fn();
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
    // The modal confirm button is labelled exactly "Delete"
    const confirmBtn = await screen.findByRole('button', { name: /^delete$/i });
    fireEvent.click(confirmBtn);
    expect(onDelete).toHaveBeenCalledWith(42);
  });
});
