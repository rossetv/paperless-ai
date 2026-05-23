import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SourceDocument, SearchStats } from '../../../api/types';
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
  tags: [],
});

const stats: SearchStats = { llm_calls: 3, latency_ms: 1842, refined: false };

describe('AnswerCard', () => {
  it('renders the answer text', () => {
    render(
      <AnswerCard
        answer="The boiler was installed in 2021."
        sources={[makeSource(1)]}
        stats={stats}
      />,
    );
    expect(
      screen.getByText(/The boiler was installed in 2021/),
    ).toBeInTheDocument();
  });

  it('renders a citation button for each inline [n] marker', () => {
    render(
      <AnswerCard
        answer="The boiler [1] was fitted by a contractor [2] in 2021."
        sources={[makeSource(1), makeSource(2)]}
        stats={stats}
      />,
    );
    expect(
      screen.getByRole('button', { name: /view source 1/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /view source 2/i }),
    ).toBeInTheDocument();
  });

  it('enriches the citation accessible name with the source title', () => {
    render(
      <AnswerCard
        answer="The boiler [1] was fitted in 2021."
        sources={[makeSource(1)]}
        stats={stats}
      />,
    );
    // makeSource(1) yields title "Document 1"
    expect(
      screen.getByRole('button', { name: /view source 1: document 1/i }),
    ).toBeInTheDocument();
  });

  it('calls onCitationActivate with the index when a citation is clicked', async () => {
    const handler = vi.fn();
    render(
      <AnswerCard
        answer="The boiler [1] was fitted in 2021."
        sources={[makeSource(1)]}
        stats={stats}
        onCitationActivate={handler}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /view source 1/i }));
    expect(handler).toHaveBeenCalledWith(1);
  });

  it('renders an out-of-range [n] marker as plain text, not a button', () => {
    render(
      <AnswerCard
        answer="An unknown citation [9] appears here."
        sources={[makeSource(1)]}
        stats={stats}
      />,
    );
    expect(screen.getByText(/\[9\]/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /view source 9/i }),
    ).not.toBeInTheDocument();
  });

  it('resolves a [document_id] marker to the source 1-based index', async () => {
    // The synthesiser emits raw paperless document ids in citation markers,
    // not 1-based positions. The card should resolve [684] against the
    // sources list and render a citation with the source's 1-based index.
    const handler = vi.fn();
    render(
      <AnswerCard
        answer="The bill paid [684] for that month."
        sources={[makeSource(631), makeSource(684), makeSource(652)]}
        stats={stats}
        onCitationActivate={handler}
      />,
    );
    // 684 is the second source — 1-based index 2 — so the affordance is
    // labelled "View source 2".
    const button = screen.getByRole('button', { name: /view source 2/i });
    expect(button).toBeInTheDocument();
    await userEvent.click(button);
    expect(handler).toHaveBeenCalledWith(2);
  });

  it('shows the provenance footer source count', () => {
    render(
      <AnswerCard
        answer="An answer."
        sources={[makeSource(1), makeSource(2)]}
        stats={stats}
      />,
    );
    expect(screen.getByText(/2 sources/i)).toBeInTheDocument();
  });

  it('shows the refined marker when stats.refined is true', () => {
    render(
      <AnswerCard
        answer="An answer."
        sources={[makeSource(1)]}
        stats={{ ...stats, refined: true }}
      />,
    );
    expect(screen.getByText(/refined once/i)).toBeInTheDocument();
  });
});
