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
});
