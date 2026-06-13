import { render, screen } from '@testing-library/react';
import { AnswerSurface } from './AnswerSurface';

describe('AnswerSurface', () => {
  it('renders the answer prose children', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>the answer prose</span>
      </AnswerSurface>,
    );
    expect(screen.getByText('the answer prose')).toBeInTheDocument();
  });

  it('renders the "Synthesised answer" eyebrow', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText(/synthesised answer/i)).toBeInTheDocument();
  });

  it('renders the source count in the footer', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText(/4 sources/i)).toBeInTheDocument();
  });

  it('uses the singular "source" for a single source', () => {
    render(
      <AnswerSurface sourceCount={1} latencyMs={500}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText(/1 source\b/i)).toBeInTheDocument();
  });

  it('renders the latency in seconds', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText(/1\.8\s*s/i)).toBeInTheDocument();
  });

  it('renders the "Refined once" marker when refined', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842} refined>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText(/refined once/i)).toBeInTheDocument();
  });

  it('omits the refined marker by default', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.queryByText(/refined once/i)).not.toBeInTheDocument();
  });

  it('renders an <article> element', () => {
    const { container } = render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(container.querySelector('article')).toBeInTheDocument();
  });

  it('renders the cost chip when a costLabel is given', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842} costLabel="3.4k tok · $0.012">
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText('3.4k tok · $0.012')).toBeInTheDocument();
  });

  it('omits the cost chip by default', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842}>
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.queryByText(/tok/)).not.toBeInTheDocument();
  });

  it('renders a tokens-only aggregate label without a dollar figure or price note', () => {
    render(
      <AnswerSurface sourceCount={4} latencyMs={1842} costLabel="29k tok">
        <span>x</span>
      </AnswerSurface>,
    );
    expect(screen.getByText('29k tok')).toBeInTheDocument();
    expect(screen.queryByText(/prices as of/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });
});
