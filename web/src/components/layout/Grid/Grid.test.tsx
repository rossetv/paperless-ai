import { render, screen } from '@testing-library/react';
import { Grid } from './Grid';

describe('Grid', () => {
  it('renders its children', () => {
    render(<Grid columns={2}><span>Cell A</span><span>Cell B</span></Grid>);
    expect(screen.getByText('Cell A')).toBeInTheDocument();
    expect(screen.getByText('Cell B')).toBeInTheDocument();
  });

  it('renders as a <div> element', () => {
    const { container } = render(<Grid columns={2}>Content</Grid>);
    expect((container.firstChild as Element).tagName).toBe('DIV');
  });

  it('applies the base grid class', () => {
    const { container } = render(<Grid columns={2}>Content</Grid>);
    expect((container.firstChild as Element).className).toMatch(/grid/);
  });

  it('applies the columns class for the given columns count', () => {
    const { container } = render(<Grid columns={3}>Content</Grid>);
    expect((container.firstChild as Element).className).toMatch(/columns-3/);
  });

  it('applies the columns-2 class when columns is 2', () => {
    const { container } = render(<Grid columns={2}>Content</Grid>);
    expect((container.firstChild as Element).className).toMatch(/columns-2/);
  });

  it('applies a gap class when gap is provided', () => {
    const { container } = render(<Grid columns={2} gap={8}>Content</Grid>);
    expect((container.firstChild as Element).className).toMatch(/gap-8/);
  });

  it('does not apply a gap class when gap is omitted', () => {
    const { container } = render(<Grid columns={2}>Content</Grid>);
    expect((container.firstChild as Element).className).not.toMatch(/gap-/);
  });

  it('forwards a custom className', () => {
    const { container } = render(<Grid columns={2} className="custom">Content</Grid>);
    expect((container.firstChild as Element).className).toContain('custom');
  });
});
