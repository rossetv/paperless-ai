import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DocumentErrorScreen } from './DocumentErrorScreen';

describe('DocumentErrorScreen', () => {
  it('renders the not-found variant when notFound is true', () => {
    render(<DocumentErrorScreen notFound={true} />);
    expect(screen.getByText('Document not found')).toBeInTheDocument();
    expect(
      screen.getByText('This document is no longer in the index.'),
    ).toBeInTheDocument();
  });

  it('renders the generic-error variant when notFound is false', () => {
    render(<DocumentErrorScreen notFound={false} />);
    expect(screen.getByText('Could not load document')).toBeInTheDocument();
    expect(
      screen.getByText('The document is unavailable. Try again in a moment.'),
    ).toBeInTheDocument();
  });
});
