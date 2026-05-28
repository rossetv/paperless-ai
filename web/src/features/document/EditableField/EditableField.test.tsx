import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditableField } from './EditableField';

describe('EditableField', () => {
  it('renders the value as static text when canEdit=false', () => {
    render(<EditableField label="ASN" value="123" canEdit={false} onCommit={vi.fn()} />);
    expect(screen.getByText('123')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('renders placeholder when value is empty and canEdit=false', () => {
    render(<EditableField label="ASN" value="" canEdit={false} placeholder="—" onCommit={vi.fn()} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('switches to input on click when canEdit=true', () => {
    render(<EditableField label="ASN" value="123" canEdit={true} onCommit={vi.fn()} />);
    fireEvent.click(screen.getByText('123'));
    expect(screen.getByRole('textbox')).toHaveValue('123');
  });

  it('commits on Enter', () => {
    const onCommit = vi.fn();
    render(<EditableField label="ASN" value="123" canEdit={true} onCommit={onCommit} />);
    fireEvent.click(screen.getByText('123'));
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '456' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledWith('456');
  });

  it('commits on blur', () => {
    const onCommit = vi.fn();
    render(<EditableField label="ASN" value="123" canEdit={true} onCommit={onCommit} />);
    fireEvent.click(screen.getByText('123'));
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '456' } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith('456');
  });

  it('reverts on Escape', () => {
    const onCommit = vi.fn();
    render(<EditableField label="ASN" value="123" canEdit={true} onCommit={onCommit} />);
    fireEvent.click(screen.getByText('123'));
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '999' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByText('123')).toBeInTheDocument();
  });

  it('does not call onCommit when value did not change', () => {
    const onCommit = vi.fn();
    render(<EditableField label="ASN" value="123" canEdit={true} onCommit={onCommit} />);
    fireEvent.click(screen.getByText('123'));
    fireEvent.blur(screen.getByRole('textbox'));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('passes type to the input (date)', () => {
    render(<EditableField label="Date" value="2026-05-22" canEdit={true} type="date" onCommit={vi.fn()} />);
    fireEvent.click(screen.getByText('2026-05-22'));
    expect(screen.getByDisplayValue('2026-05-22').getAttribute('type')).toBe('date');
  });
});
