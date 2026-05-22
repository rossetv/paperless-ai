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

  it('sandboxes the iframe with no script or same-origin grant', () => {
    // The src is same-origin with the app; an empty sandbox denies any
    // active content script execution and same-origin access — the
    // stored-XSS defence-in-depth layer. allow-scripts must not appear.
    render(<PdfFrame src="/api/documents/9823/pdf" title="t" />);
    const frame = screen.getByTitle('t');
    expect(frame).toHaveAttribute('sandbox', '');
  });
});
