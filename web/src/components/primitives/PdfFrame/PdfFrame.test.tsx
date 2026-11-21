import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
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
    // Chrome's native PDF viewer paints blank under a fully locked sandbox. The
    // backend pins Content-Type: application/pdf with nosniff
    // (src/search/document_routes/_proxy.py), so the iframe carries no sandbox.
    render(<PdfFrame src="/api/documents/9823/pdf" title="t" />);
    const frame = screen.getByTitle('t');
    expect(frame).not.toHaveAttribute('sandbox');
  });

  // A refused-framing or stalled stream fires neither `load` nor a reliable
  // `error`, so a load timeout is the authoritative failure signal; `onError` is
  // only an early-out for browsers that do fire it.
  describe('load-failure reporting', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('reports failure when the frame never loads within the grace window', () => {
      const onLoadError = vi.fn();
      render(<PdfFrame src="/x" title="t" onLoadError={onLoadError} />);
      expect(onLoadError).not.toHaveBeenCalled();
      vi.advanceTimersByTime(8000);
      expect(onLoadError).toHaveBeenCalledTimes(1);
    });

    it('does not report failure after a successful load', () => {
      const onLoadError = vi.fn();
      render(<PdfFrame src="/x" title="t" onLoadError={onLoadError} />);
      fireEvent.load(screen.getByTitle('t'));
      vi.advanceTimersByTime(8000);
      expect(onLoadError).not.toHaveBeenCalled();
    });

    it('reports failure at most once', () => {
      const onLoadError = vi.fn();
      render(<PdfFrame src="/x" title="t" onLoadError={onLoadError} />);
      vi.advanceTimersByTime(8000);
      vi.advanceTimersByTime(8000);
      expect(onLoadError).toHaveBeenCalledTimes(1);
    });
  });
});
