import { render, screen } from '@testing-library/react';
import { PdfFrame } from './PdfFrame';

describe('PdfFrame', () => {
  it('renders an iframe pointed at the src', () => {
    render(<PdfFrame src="/api/documents/9823/pdf" title="Annual statement" />);
    const frame = screen.getByTitle('Annual statement');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('src', '/api/documents/9823/pdf');
  });

  it('uses the title as the iframe accessible name', () => {
    render(<PdfFrame src="/x" title="My document PDF" />);
    expect(screen.getByTitle('My document PDF')).toBeInTheDocument();
  });

  it('merges a custom className onto the wrapper', () => {
    const { container } = render(
      <PdfFrame src="/x" title="t" className="extra" />,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });

  it('does not lock the iframe with sandbox=""', () => {
    // Chrome's native PDF viewer refuses to render under a fully-locked
    // sandbox — the iframe paints blank. The active-content vector is
    // already neutralised by the backend pinning Content-Type:
    // application/pdf with X-Content-Type-Options: nosniff
    // (document_routes.py), so the sandbox layer is dropped.
    render(<PdfFrame src="/api/documents/9823/pdf" title="t" />);
    const frame = screen.getByTitle('t');
    expect(frame).not.toHaveAttribute('sandbox');
  });
});
