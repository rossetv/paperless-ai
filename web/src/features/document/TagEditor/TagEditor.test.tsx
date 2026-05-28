import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TagEditor } from './TagEditor';

const ALL = [
  { id: 10, name: '2026', document_count: 50 },
  { id: 11, name: 'invoice', document_count: 30 },
  { id: 12, name: 'paye', document_count: 20 },
];

describe('TagEditor', () => {
  it('renders selected tags as chips', () => {
    render(
      <TagEditor selectedIds={[10, 12]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.getByText('2026')).toBeInTheDocument();
    expect(screen.getByText('paye')).toBeInTheDocument();
    expect(screen.queryByText('invoice')).not.toBeInTheDocument();
  });

  it('calls onRemove when × is clicked', () => {
    const onRemove = vi.fn();
    render(
      <TagEditor selectedIds={[10]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={onRemove} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /remove 2026/i }));
    expect(onRemove).toHaveBeenCalledWith(10);
  });

  it('add-button opens a combobox that excludes already-selected tags', () => {
    render(
      <TagEditor selectedIds={[10]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    // The combobox listbox should show invoice + paye but NOT 2026 (already selected).
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByText('invoice')).toBeInTheDocument();
    expect(screen.getByText('paye')).toBeInTheDocument();
    // 2026 chip is still rendered above the combobox, but no '2026' option inside the listbox.
    const list = screen.getByRole('listbox');
    expect(list.textContent ?? '').not.toMatch(/2026/);
  });

  it('clicking an option calls onAdd', () => {
    const onAdd = vi.fn();
    render(
      <TagEditor selectedIds={[]} availableTags={ALL}
        canEdit={true} onAdd={onAdd} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByText('invoice'));
    expect(onAdd).toHaveBeenCalledWith(11);
  });

  it('offers create-new for unknown text', () => {
    const onCreate = vi.fn();
    render(
      <TagEditor selectedIds={[]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={onCreate} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'urgent' } });
    fireEvent.click(screen.getByText(/create "urgent"/i));
    expect(onCreate).toHaveBeenCalledWith('urgent');
  });

  it('does not offer create when the query exactly matches an existing tag (case-insensitive)', () => {
    render(
      <TagEditor selectedIds={[]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'INVOICE' } });
    expect(screen.queryByText(/create "invoice"/i)).not.toBeInTheDocument();
  });

  it('renders an unknown-id chip as #<id> but still removable', () => {
    const onRemove = vi.fn();
    render(
      <TagEditor selectedIds={[10, 999]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={onRemove} onCreate={vi.fn()} />,
    );
    expect(screen.getByText('#999')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /remove #999/i }));
    expect(onRemove).toHaveBeenCalledWith(999);
  });

  it('canEdit=false hides × and the add button', () => {
    render(
      <TagEditor selectedIds={[10]} availableTags={ALL}
        canEdit={false} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add tag/i })).not.toBeInTheDocument();
    // Chip text still rendered:
    expect(screen.getByText('2026')).toBeInTheDocument();
  });
});
