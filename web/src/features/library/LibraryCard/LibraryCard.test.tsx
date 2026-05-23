import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryCard } from './LibraryCard';
import type { LibraryDocument } from '../../../api/types';

function makeDoc(overrides: Partial<LibraryDocument> = {}): LibraryDocument {
  return {
    id: 42,
    title: 'Annual energy statement — 2024',
    correspondent: 'Npower Energy',
    document_type: 'Statement',
    created: '2025-01-12',
    tags: ['Energy', '2024'],
    page_count: 6,
    ...overrides,
  };
}

describe('LibraryCard', () => {
  it('renders the document title', () => {
    render(<LibraryCard document={makeDoc()} onOpen={vi.fn()} />);
    expect(
      screen.getByText('Annual energy statement — 2024'),
    ).toBeInTheDocument();
  });

  it('renders the correspondent', () => {
    render(<LibraryCard document={makeDoc()} onOpen={vi.fn()} />);
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
  });

  it('renders the created date in short British form', () => {
    render(<LibraryCard document={makeDoc({ created: '2025-01-12' })} onOpen={vi.fn()} />);
    expect(screen.getByText('12 Jan 2025')).toBeInTheDocument();
  });

  it('renders an em dash when there is no created date', () => {
    render(<LibraryCard document={makeDoc({ created: null })} onOpen={vi.fn()} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('falls back to "Untitled document" when title is null', () => {
    render(<LibraryCard document={makeDoc({ title: null })} onOpen={vi.fn()} />);
    expect(screen.getByText('Untitled document')).toBeInTheDocument();
  });

  it('renders the document type and every tag', () => {
    render(
      <LibraryCard
        document={makeDoc({ document_type: 'Statement', tags: ['Energy', '2024'] })}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText('Statement')).toBeInTheDocument();
    expect(screen.getByText('#Energy')).toBeInTheDocument();
    expect(screen.getByText('#2024')).toBeInTheDocument();
  });

  it('omits the type chip when document_type is null', () => {
    render(<LibraryCard document={makeDoc({ document_type: null })} onOpen={vi.fn()} />);
    expect(screen.queryByText('Statement')).not.toBeInTheDocument();
  });

  it('calls onOpen with the document id when clicked', async () => {
    const onOpen = vi.fn();
    render(<LibraryCard document={makeDoc()} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledWith(42);
  });

  it('gives the button an accessible name including the title', () => {
    render(<LibraryCard document={makeDoc()} onOpen={vi.fn()} />);
    expect(
      screen.getByRole('button', { name: /Annual energy statement/ }),
    ).toBeInTheDocument();
  });

  it('renders a real thumbnail <img> by default', () => {
    const { container } = render(<LibraryCard document={makeDoc()} onOpen={vi.fn()} />);
    // alt="" gives the image role="presentation"; query by tag name.
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect((img as HTMLImageElement).src).toContain('/api/documents/42/thumb');
  });

  it('falls back to the DocThumb SVG when the image errors', () => {
    const { container } = render(<LibraryCard document={makeDoc()} onOpen={vi.fn()} />);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    fireEvent.error(img!);
    // After error the SVG fallback is rendered and the broken <img> is gone.
    expect(container.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(container.querySelector('img')).toBeNull();
  });

  it('merges a caller className onto the button root', () => {
    const { container } = render(
      <LibraryCard document={makeDoc()} onOpen={vi.fn()} className="extra" />,
    );
    expect(container.firstChild).toHaveClass('extra');
  });
});
