import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TaxonomyCombobox } from './TaxonomyCombobox';

const ITEMS = [
  { id: 1, name: 'eBay', document_count: 87 },
  { id: 2, name: 'eBay Europe Services IRL', document_count: 14 },
];

describe('TaxonomyCombobox', () => {
  it('renders the selected value as a static button when closed', () => {
    render(
      <TaxonomyCombobox
        label="Correspondent"
        items={ITEMS}
        selectedId={1}
        canEdit={true}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /ebay/i })).toBeInTheDocument();
  });

  it('shows "—" placeholder when no selectedId', () => {
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: /—/ })).toBeInTheDocument();
  });

  it('opens a listbox on click and filters by typed text', () => {
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'europe' } });
    expect(screen.getByText(/europe services/i)).toBeInTheDocument();
    expect(screen.queryByText(/^eBay$/)).not.toBeInTheDocument();
  });

  it('calls onSelect when an option is clicked', () => {
    const onSelect = vi.fn();
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={onSelect} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button'));
    fireEvent.click(screen.getByText('eBay'));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('closes the dropdown after selecting an option', () => {
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button'));
    fireEvent.click(screen.getByText('eBay'));
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('offers a "Create <text>" option when no exact match', () => {
    const onCreate = vi.fn();
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={vi.fn()} onCreate={onCreate} />,
    );
    fireEvent.click(screen.getByRole('button'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Brand New Co' } });
    fireEvent.click(screen.getByText(/create "brand new co"/i));
    expect(onCreate).toHaveBeenCalledWith('Brand New Co');
  });

  it('does not offer "Create" when an exact match exists (case-insensitive)', () => {
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={vi.fn()} onCreate={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'EBAY' } });
    expect(screen.queryByText(/create "ebay"/i)).not.toBeInTheDocument();
  });

  it('closes on Escape without firing onSelect/onCreate', () => {
    const onSelect = vi.fn();
    const onCreate = vi.fn();
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={null}
        canEdit={true} onSelect={onSelect} onCreate={onCreate} />,
    );
    fireEvent.click(screen.getByRole('button'));
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' });
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('renders static text when canEdit=false', () => {
    render(
      <TaxonomyCombobox label="Correspondent" items={ITEMS} selectedId={1}
        canEdit={false} onSelect={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('eBay')).toBeInTheDocument();
  });
});
