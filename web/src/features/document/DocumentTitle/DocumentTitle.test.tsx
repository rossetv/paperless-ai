import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DocumentTitle } from './DocumentTitle';

describe('DocumentTitle', () => {
  // ── Read-only mode ──────────────────────────────────────────────────────────

  it('renders the title as a heading (canEdit=false)', () => {
    render(<DocumentTitle title="An invoice" canEdit={false} onChange={() => {}} />);
    expect(screen.getByRole('heading', { name: 'An invoice' })).toBeInTheDocument();
  });

  it('falls back to "Untitled document" when title is null', () => {
    render(<DocumentTitle title={null} canEdit={false} onChange={() => {}} />);
    expect(screen.getByRole('heading', { name: /untitled document/i })).toBeInTheDocument();
  });

  it('canEdit=false renders a plain heading without a button role', () => {
    render(<DocumentTitle title="An invoice" canEdit={false} onChange={() => {}} />);
    expect(screen.getByRole('heading', { name: 'An invoice' })).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  // ── Editable mode ───────────────────────────────────────────────────────────

  it('switches to input on click when canEdit=true', () => {
    render(<DocumentTitle title="An invoice" canEdit={true} onChange={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /an invoice/i }));
    expect(screen.getByDisplayValue('An invoice')).toBeInTheDocument();
  });

  it('calls onChange with the trimmed new value on Enter', () => {
    const onChange = vi.fn();
    render(<DocumentTitle title="An invoice" canEdit={true} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /an invoice/i }));
    const input = screen.getByDisplayValue('An invoice');
    fireEvent.change(input, { target: { value: 'Renamed  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('Renamed');
  });

  it('reverts on Escape', () => {
    const onChange = vi.fn();
    render(<DocumentTitle title="An invoice" canEdit={true} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /an invoice/i }));
    const input = screen.getByDisplayValue('An invoice');
    fireEvent.change(input, { target: { value: 'something' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not fire onChange when value is unchanged on blur', () => {
    const onChange = vi.fn();
    render(<DocumentTitle title="An invoice" canEdit={true} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /an invoice/i }));
    fireEvent.blur(screen.getByDisplayValue('An invoice'));
    expect(onChange).not.toHaveBeenCalled();
  });
});
