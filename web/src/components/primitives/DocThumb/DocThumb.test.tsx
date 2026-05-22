import { render } from '@testing-library/react';
import { DocThumb } from './DocThumb';

describe('DocThumb', () => {
  it('renders an SVG element', () => {
    const { container } = render(<DocThumb />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('is decorative — the svg is aria-hidden', () => {
    const { container } = render(<DocThumb />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('renders body line-stripe rects', () => {
    const { container } = render(<DocThumb kind="statement" />);
    // header + hairline + body stripes + footer — well over five rects
    expect(container.querySelectorAll('rect').length).toBeGreaterThan(5);
  });

  it('draws the matched rows in the accent colour', () => {
    const { container } = render(<DocThumb kind="statement" matched={[3, 4]} />);
    const accented = Array.from(container.querySelectorAll('rect')).filter(
      (r) => r.getAttribute('fill') === 'var(--colour-accent)',
    );
    // exactly the two matched body rows
    expect(accented).toHaveLength(2);
  });

  it('draws no accented rows when matched is empty', () => {
    const { container } = render(<DocThumb kind="letter" matched={[]} />);
    const accented = Array.from(container.querySelectorAll('rect')).filter(
      (r) => r.getAttribute('fill') === 'var(--colour-accent)',
    );
    expect(accented).toHaveLength(0);
  });

  it('renders a footer band for the statement kind', () => {
    const { container } = render(<DocThumb kind="statement" />);
    expect(container.querySelector('[data-doc-footer]')).toBeInTheDocument();
  });

  it('renders no footer band for the letter kind', () => {
    const { container } = render(<DocThumb kind="letter" />);
    expect(container.querySelector('[data-doc-footer]')).not.toBeInTheDocument();
  });

  it('merges a custom className onto the wrapper', () => {
    const { container } = render(<DocThumb className="extra" />);
    expect((container.firstChild as Element).className).toContain('extra');
  });

  it('applies the data-testid when provided', () => {
    const { container } = render(<DocThumb data-testid="thumb" />);
    expect(container.querySelector('[data-testid="thumb"]')).toBeInTheDocument();
  });
});
