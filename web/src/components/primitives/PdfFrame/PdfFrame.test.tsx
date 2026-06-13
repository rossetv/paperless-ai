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
    // Chrome's native PDF viewer refuses to render under a fully-locked
    // sandbox — the iframe paints blank. The active-content vector is
    // already neutralised by the backend pinning Content-Type:
    // application/pdf with X-Content-Type-Options: nosniff
    // (document_routes.py), so the sandbox layer is dropped.
    render(<PdfFrame src="/api/documents/9823/pdf" title="t" />);
    const frame = screen.getByTitle('t');
    expect(frame).not.toHaveAttribute('sandbox');
  });

  // Failure is detected by a load timeout: a refused-framing or stalled stream
  // never fires `load` *or* a reliable `error` event (the iframe `error` event
  // is famously inconsistent across browsers — that unreliability is exactly
  // why the timeout is the authoritative signal). The iframe still carries an
  // `onError` handler as a cheap early-out for the browsers that do fire it.
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
