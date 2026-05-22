import { render, screen } from '@testing-library/react';
import { SourceCardSurface } from './SourceCardSurface';

describe('SourceCardSurface', () => {
  it('renders its children content', () => {
    render(
      <SourceCardSurface index={1} thumbKind="statement">
        <p>card body</p>
      </SourceCardSurface>,
    );
    expect(screen.getByText('card body')).toBeInTheDocument();
  });

  it('renders an <article> element', () => {
    const { container } = render(
      <SourceCardSurface index={1} thumbKind="invoice">
        <span>x</span>
      </SourceCardSurface>,
    );
    expect(container.querySelector('article')).toBeInTheDocument();
  });

  it('renders the citation index badge', () => {
    render(
      <SourceCardSurface index={3} thumbKind="letter">
        <span>x</span>
      </SourceCardSurface>,
    );
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders the document thumbnail', () => {
    const { container } = render(
      <SourceCardSurface index={1} thumbKind="statement">
        <span>x</span>
      </SourceCardSurface>,
    );
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('applies the highlighted modifier when highlighted', () => {
    const { container } = render(
      <SourceCardSurface index={1} thumbKind="statement" highlighted>
        <span>x</span>
      </SourceCardSurface>,
    );
    expect((container.firstChild as Element).className).toMatch(/highlighted/);
  });

  it('does not apply the highlighted modifier by default', () => {
    const { container } = render(
      <SourceCardSurface index={1} thumbKind="statement">
        <span>x</span>
      </SourceCardSurface>,
    );
    expect((container.firstChild as Element).className).not.toMatch(/highlighted/);
  });

  it('merges a custom className', () => {
    const { container } = render(
      <SourceCardSurface index={1} thumbKind="statement" className="extra">
        <span>x</span>
      </SourceCardSurface>,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
