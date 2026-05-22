import { render, screen } from '@testing-library/react';
import { IndexStatusFooter } from './IndexStatusFooter';

describe('IndexStatusFooter', () => {
  it('renders the document and chunk counts', () => {
    render(
      <IndexStatusFooter
        documentCount={14238}
        chunkCount={187612}
        embeddingModel="text-embedding-3-small"
      />,
    );
    expect(screen.getByText(/14,238 documents/)).toBeInTheDocument();
    expect(screen.getByText(/187,612 chunks/)).toBeInTheDocument();
  });

  it('renders the embedding model name', () => {
    render(
      <IndexStatusFooter
        documentCount={1}
        chunkCount={2}
        embeddingModel="text-embedding-3-small"
      />,
    );
    expect(screen.getByText(/text-embedding-3-small/)).toBeInTheDocument();
  });

  it('shows an "index ready" status by default', () => {
    render(
      <IndexStatusFooter
        documentCount={1}
        chunkCount={2}
        embeddingModel="m"
      />,
    );
    expect(screen.getByText(/index ready/i)).toBeInTheDocument();
  });

  it('omits the embedding model when it is null', () => {
    render(
      <IndexStatusFooter documentCount={1} chunkCount={2} embeddingModel={null} />,
    );
    expect(screen.queryByText(/embedding/i)).not.toBeInTheDocument();
  });

  it('merges a custom className', () => {
    const { container } = render(
      <IndexStatusFooter
        documentCount={1}
        chunkCount={2}
        embeddingModel="m"
        className="extra"
      />,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
