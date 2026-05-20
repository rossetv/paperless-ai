import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SourceDocument } from '../../../api/types';
import { AnswerCard } from './AnswerCard';

const makeSource = (id: number): SourceDocument => ({
  document_id: id,
  title: `Document ${id}`,
  correspondent: 'HMRC',
  document_type: 'Letter',
  created: '2024-01-01',
  snippet: 'Some text snippet',
  paperless_url: `https://paperless.example.com/documents/${id}/`,
  score: 0.9,
});

describe('AnswerCard', () => {
  it('renders the answer text', () => {
    const sources = [makeSource(1)];
    render(<AnswerCard answer="The boiler was installed in 2021." sources={sources} />);
    expect(screen.getByText(/The boiler was installed in 2021/)).toBeInTheDocument();
  });

  it('renders citation [n] buttons for each inline marker in the answer', () => {
    const sources = [makeSource(1), makeSource(2)];
    render(
      <AnswerCard
        answer="The boiler [1] was installed by a contractor [2] in 2021."
        sources={sources}
      />,
    );
    // Two citation buttons rendered
    expect(screen.getByRole('button', { name: /citation 1/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /citation 2/i })).toBeInTheDocument();
  });

  it('calls onCitationActivate with the correct index when a citation is clicked', async () => {
    const handler = vi.fn();
    const sources = [makeSource(1), makeSource(2)];
    render(
      <AnswerCard
        answer="See [1] and also [2] for more."
        sources={sources}
        onCitationActivate={handler}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /citation 2/i }));
    expect(handler).toHaveBeenCalledWith(2);
  });

  it('renders plain text segments between citation markers', () => {
    const sources = [makeSource(1)];
    render(<AnswerCard answer="Before [1] after." sources={sources} />);
    expect(screen.getByText(/Before/)).toBeInTheDocument();
    expect(screen.getByText(/after/)).toBeInTheDocument();
  });

  it('renders answer with no citations as plain text', () => {
    render(<AnswerCard answer="No citations here." sources={[]} />);
    expect(screen.getByText('No citations here.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /citation/i })).not.toBeInTheDocument();
  });

  it('renders as an article element for semantic correctness', () => {
    render(<AnswerCard answer="Answer." sources={[]} />);
    // Card uses `as="article"` — the article element should be present
    expect(document.querySelector('article')).toBeInTheDocument();
  });
});
