import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { IndexStatusPill } from './IndexStatusPill';

vi.mock('../../../api/hooks', () => ({
  useStats: vi.fn(),
}));

import { useStats } from '../../../api/hooks';
const mockUseStats = useStats as ReturnType<typeof vi.fn>;

describe('IndexStatusPill', () => {
  it('renders nothing while the stats query is loading', () => {
    mockUseStats.mockReturnValue({ isSuccess: false, data: undefined });
    const { container } = render(<IndexStatusPill />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the document count when stats resolve successfully', () => {
    mockUseStats.mockReturnValue({
      isSuccess: true,
      data: {
        document_count: 123,
        chunk_count: 4000,
        last_reconcile_at: null,
        embedding_model: 'text-embedding-3-small',
      },
    });
    render(<IndexStatusPill />);
    expect(screen.getByText(/123/)).toBeInTheDocument();
  });

  it('renders an aria-label that includes the document count', () => {
    mockUseStats.mockReturnValue({
      isSuccess: true,
      data: {
        document_count: 7,
        chunk_count: 200,
        last_reconcile_at: null,
        embedding_model: 'text-embedding-3-small',
      },
    });
    render(<IndexStatusPill />);
    expect(screen.getByLabelText(/Index ready, 7 documents/)).toBeInTheDocument();
  });

  it('renders nothing when isSuccess is true but data is undefined', () => {
    mockUseStats.mockReturnValue({ isSuccess: true, data: undefined });
    const { container } = render(<IndexStatusPill />);
    expect(container.firstChild).toBeNull();
  });
});
