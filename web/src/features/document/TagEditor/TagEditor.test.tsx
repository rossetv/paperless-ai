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
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByText('invoice')).toBeInTheDocument();
    expect(screen.getByText('paye')).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('option', { name: /create/i }));
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

  it('does not offer create when the typed name matches an ALREADY-SELECTED tag (regression: no duplicate minting)', () => {
    // "invoice" is already selected, so it is not in the dropdown; its exact
    // name must still not offer "Create".
    const onCreate = vi.fn();
    render(
      <TagEditor selectedIds={[11]} availableTags={ALL}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={onCreate} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'invoice' } });
    expect(screen.queryByRole('option', { name: /create/i })).not.toBeInTheDocument();
    expect(onCreate).not.toHaveBeenCalled();
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
    expect(screen.getByText('2026')).toBeInTheDocument();
  });

  it('counts one document as "1 doc", not "1 docs"', () => {
    render(
      <TagEditor selectedIds={[]} availableTags={[{ id: 1, name: 'solo', document_count: 1 }, ...ALL]}
        canEdit={true} onAdd={vi.fn()} onRemove={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    expect(screen.getByText('1 doc')).toBeInTheDocument();
    expect(screen.getByText('30 docs')).toBeInTheDocument();
  });

  describe('focus after removing a tag', () => {
    function Harness({ initial }: { initial: number[] }): React.ReactElement {
      const [ids, setIds] = React.useState(initial);
      return (
        <TagEditor selectedIds={ids} availableTags={ALL} canEdit={true} onAdd={vi.fn()}
          onRemove={(id) => setIds((cur) => cur.filter((x) => x !== id))} onCreate={vi.fn()} />
      );
    }

    it('moves to the next chip', () => {
      render(<Harness initial={[10, 11, 12]} />);
      fireEvent.click(screen.getByRole('button', { name: 'Remove 2026' }));
      expect(screen.getByRole('button', { name: 'Remove invoice' })).toHaveFocus();
    });

    it('moves to the previous chip when the last one is removed', () => {
      render(<Harness initial={[10, 11, 12]} />);
      fireEvent.click(screen.getByRole('button', { name: 'Remove paye' }));
      expect(screen.getByRole('button', { name: 'Remove invoice' })).toHaveFocus();
    });

    it('moves to the Add tag button when no chip is left', () => {
      render(<Harness initial={[10]} />);
      fireEvent.click(screen.getByRole('button', { name: 'Remove 2026' }));
      expect(screen.getByRole('button', { name: /add tag/i })).toHaveFocus();
    });
  });
});
