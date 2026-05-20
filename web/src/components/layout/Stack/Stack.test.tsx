import { render, screen } from '@testing-library/react';
import { Stack } from './Stack';

describe('Stack', () => {
  it('renders its children', () => {
    render(<Stack><span>Item A</span><span>Item B</span></Stack>);
    expect(screen.getByText('Item A')).toBeInTheDocument();
    expect(screen.getByText('Item B')).toBeInTheDocument();
  });

  it('renders as a <div> element by default', () => {
    const { container } = render(<Stack>Content</Stack>);
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });

  it('applies the base stack class', () => {
    const { container } = render(<Stack>Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/stack/);
  });

  it('applies the vertical direction class by default', () => {
    const { container } = render(<Stack>Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/vertical/);
  });

  it('applies the horizontal direction class when direction is horizontal', () => {
    const { container } = render(<Stack direction="horizontal">Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/horizontal/);
  });

  it('applies a gap class corresponding to the gap prop', () => {
    const { container } = render(<Stack gap={6}>Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/gap-6/);
  });

  it('applies the align-start class when align is start', () => {
    const { container } = render(<Stack align="start">Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/align-start/);
  });

  it('applies the align-center class when align is center', () => {
    const { container } = render(<Stack align="center">Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/align-center/);
  });

  it('applies the justify-between class when justify is between', () => {
    const { container } = render(<Stack justify="between">Content</Stack>);
    expect((container.firstChild as Element).className).toMatch(/justify-between/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Stack className="custom">Content</Stack>);
    expect((container.firstChild as Element).className).toContain('custom');
  });
});
