import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DocumentTitle } from './DocumentTitle';

describe('DocumentTitle', () => {
  it('renders the title as a heading', () => {
    render(<DocumentTitle title="An invoice" canEdit={false} onChange={() => {}} />);
    expect(screen.getByRole('heading', { name: 'An invoice' })).toBeInTheDocument();
  });

  it('falls back to "Untitled document" when title is null', () => {
    render(<DocumentTitle title={null} canEdit={false} onChange={() => {}} />);
    expect(screen.getByRole('heading', { name: /untitled document/i })).toBeInTheDocument();
  });
});
