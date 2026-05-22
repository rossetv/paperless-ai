import { render, screen } from '@testing-library/react';
import { SnippetText } from './SnippetText';

describe('SnippetText', () => {
  it('renders plain snippet text', () => {
    render(<SnippetText text="A plain closing balance of zero." />);
    expect(
      screen.getByText(/A plain closing balance of zero/),
    ).toBeInTheDocument();
  });

  it('highlights a **bold** run as a mark element', () => {
    const { container } = render(
      <SnippetText text="Total charges were **£1,847.32** last year." />,
    );
    const marks = container.querySelectorAll('mark');
    expect(marks).toHaveLength(1);
    expect(marks[0]).toHaveTextContent('£1,847.32');
  });

  it('highlights multiple bold runs', () => {
    const { container } = render(
      <SnippetText text="**Twelve** direct debits of **£153.94** each." />,
    );
    expect(container.querySelectorAll('mark')).toHaveLength(2);
  });

  it('renders an empty snippet as an accessible notice', () => {
    render(<SnippetText text="" />);
    expect(screen.getByText(/no excerpt available/i)).toBeInTheDocument();
  });

  it('does not render a mark when there is no bold run', () => {
    const { container } = render(<SnippetText text="No emphasis here." />);
    expect(container.querySelector('mark')).not.toBeInTheDocument();
  });

  it('merges a custom className onto the paragraph', () => {
    const { container } = render(
      <SnippetText text="text" className="extra" />,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
