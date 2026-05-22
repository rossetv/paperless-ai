import { render, screen } from '@testing-library/react';
import { Brand } from './Brand';

describe('Brand', () => {
  it('renders an SVG element', () => {
    const { container } = render(<Brand />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('defaults to 22 px wide and tall', () => {
    const { container } = render(<Brand />);
    const svg = container.querySelector('svg')!;
    expect(svg).toHaveAttribute('width', '22');
    expect(svg).toHaveAttribute('height', '22');
  });

  it('accepts a custom size', () => {
    const { container } = render(<Brand size={32} />);
    const svg = container.querySelector('svg')!;
    expect(svg).toHaveAttribute('width', '32');
    expect(svg).toHaveAttribute('height', '32');
  });

  it('is aria-hidden by default (decorative)', () => {
    const { container } = render(<Brand />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('accepts an aria-label for non-decorative use', () => {
    const { container } = render(<Brand aria-label="Paperless AI logo" />);
    const svg = container.querySelector('svg')!;
    expect(svg).toHaveAttribute('aria-label', 'Paperless AI logo');
    expect(svg).toHaveAttribute('role', 'img');
  });

  it('renders exactly three child shapes (two rects + one circle outer + one circle inner)', () => {
    const { container } = render(<Brand />);
    const svg = container.querySelector('svg')!;
    const rects = svg.querySelectorAll('rect');
    const circles = svg.querySelectorAll('circle');
    expect(rects).toHaveLength(2);
    expect(circles).toHaveLength(2);
  });

  it('applies the data-testid when provided', () => {
    render(<Brand data-testid="brand-logo" />);
    expect(screen.getByTestId('brand-logo')).toBeInTheDocument();
  });

  it('merges a custom className onto the svg', () => {
    const { container } = render(<Brand className="custom" />);
    // SVG elements expose className as SVGAnimatedString in JSDOM, so we read
    // the attribute string directly.
    expect(container.querySelector('svg')?.getAttribute('class')).toContain('custom');
  });
});
