import { render, screen } from '@testing-library/react';
import { SearchScreenLayout } from './SearchScreenLayout';

describe('SearchScreenLayout', () => {
  it('renders the centred variant content', () => {
    render(
      <SearchScreenLayout variant="centred">
        <p>centred body</p>
      </SearchScreenLayout>,
    );
    expect(screen.getByText('centred body')).toBeInTheDocument();
  });

  it('renders the rail variant with both rail and content', () => {
    render(
      <SearchScreenLayout
        variant="rail"
        rail={<aside>rail content</aside>}
      >
        <p>main content</p>
      </SearchScreenLayout>,
    );
    expect(screen.getByText('rail content')).toBeInTheDocument();
    expect(screen.getByText('main content')).toBeInTheDocument();
  });

  it('applies the centred modifier class for the centred variant', () => {
    const { container } = render(
      <SearchScreenLayout variant="centred">
        <p>x</p>
      </SearchScreenLayout>,
    );
    expect((container.firstChild as Element).className).toMatch(/centred/);
  });

  it('applies the rail modifier class for the rail variant', () => {
    const { container } = render(
      <SearchScreenLayout variant="rail" rail={<aside>r</aside>}>
        <p>x</p>
      </SearchScreenLayout>,
    );
    expect((container.firstChild as Element).className).toMatch(/rail/);
  });

  it('does not render a rail region for the centred variant', () => {
    const { container } = render(
      <SearchScreenLayout variant="centred">
        <p>x</p>
      </SearchScreenLayout>,
    );
    expect(container.querySelector('[data-screen-rail]')).not.toBeInTheDocument();
  });

  it('merges a custom className', () => {
    const { container } = render(
      <SearchScreenLayout variant="centred" className="extra">
        <p>x</p>
      </SearchScreenLayout>,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
