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

  it('applies a custom width via inline style when width is provided', () => {
    const { container } = render(<Skeleton width="200px" />);
    const el = container.firstChild as HTMLElement;
    expect(el.style.width).toBe('200px');
  });

  it('applies a custom height via inline style when height is provided', () => {
    const { container } = render(<Skeleton height="40px" />);
    const el = container.firstChild as HTMLElement;
    expect(el.style.height).toBe('40px');
  });

  it('forwards a custom className', () => {
    const { container } = render(<Skeleton className="my-skeleton" />);
    expect((container.firstChild as Element).className).toContain('my-skeleton');
  });
});
