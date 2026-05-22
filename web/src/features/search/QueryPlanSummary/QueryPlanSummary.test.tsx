import { render, screen } from '@testing-library/react';
import type { QueryPlan, SearchStats } from '../../../api/types';
import { QueryPlanSummary } from './QueryPlanSummary';

const plan: QueryPlan = {
  semantic_queries: [
    'Total annual energy payments to Npower in 2024',
    'Direct debit schedule and upcoming collection date',
  ],
  keyword_terms: ['Npower', 'direct debit', '2024'],
  sub_questions: [],
};

const stats: SearchStats = { llm_calls: 3, latency_ms: 1842, refined: true };

describe('QueryPlanSummary', () => {
  it('renders the summary heading', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/how this answer was built/i)).toBeInTheDocument();
  });

  it('shows the semantic-query count', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/2 queries/i)).toBeInTheDocument();
  });

  it('shows the LLM call count', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/3 LLM calls/i)).toBeInTheDocument();
  });

  it('shows the latency in seconds', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/1\.84\s*s/i)).toBeInTheDocument();
  });

  it('shows the refined marker when the answer was refined', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/refined/i)).toBeInTheDocument();
  });

  it('omits the refined marker when not refined', () => {
    render(
      <QueryPlanSummary
        plan={plan}
        stats={{ ...stats, refined: false }}
      />,
    );
    expect(screen.queryByText(/refined/i)).not.toBeInTheDocument();
  });

  it('lists every semantic query in the body', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(
      screen.getByText('Total annual energy payments to Npower in 2024'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Direct debit schedule and upcoming collection date'),
    ).toBeInTheDocument();
  });

  it('lists every keyword term in the body', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText('Npower')).toBeInTheDocument();
    expect(screen.getByText('direct debit')).toBeInTheDocument();
    expect(screen.getByText('2024')).toBeInTheDocument();
  });
});
