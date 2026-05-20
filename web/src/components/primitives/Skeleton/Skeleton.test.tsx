import { render } from '@testing-library/react';
import { Skeleton } from './Skeleton';

describe('Skeleton', () => {
  it('renders a DOM element', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it('has aria-hidden="true" (decorative)', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true');
  });

  it('applies the base skeleton class', () => {
    const { container } = render(<Skeleton />);
    // CSS Modules hash class names; check className string contains 'skeleton'
    expect((container.firstChild as Element).className).toMatch(/skeleton/);
  });

  it('applies the text class when variant is "text"', () => {
    const { container } = render(<Skeleton variant="text" />);
    expect((container.firstChild as Element).className).toMatch(/text/);
  });

  it('applies the circular class when variant is "circular"', () => {
    const { container } = render(<Skeleton variant="circular" />);
    expect((container.firstChild as Element).className).toMatch(/circular/);
  });

  it('applies the rectangular class when variant is "rectangular"', () => {
    const { container } = render(<Skeleton variant="rectangular" />);
    expect((container.firstChild as Element).className).toMatch(/rectangular/);
  });

  it('applies a token-backed width class when width is provided', () => {
    const { container } = render(<Skeleton width="half" />);
    // The closed sizing API maps a named width to a CSS-module class, never an
    // inline style — so no raw CSS length leaks in.
    expect((container.firstChild as Element).className).toMatch(/width-half/);
    expect((container.firstChild as HTMLElement).style.width).toBe('');
  });

  it('applies a token-backed height class when height is provided', () => {
    const { container } = render(<Skeleton height="control" />);
    expect((container.firstChild as Element).className).toMatch(/height-control/);
    expect((container.firstChild as HTMLElement).style.height).toBe('');
  });

  it('renders one bar by default', () => {
    const { container } = render(<Skeleton variant="text" />);
    // A single bar — no multi-line wrapper.
    expect(container.querySelectorAll('span')).toHaveLength(1);
  });

  it('renders one bar per line for a multi-line text skeleton', () => {
    const { container } = render(<Skeleton variant="text" lines={3} />);
    // A wrapper span plus three line bars.
    expect(container.querySelectorAll('span')).toHaveLength(4);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Skeleton className="my-skeleton" />);
    expect((container.firstChild as Element).className).toContain('my-skeleton');
  });
});
