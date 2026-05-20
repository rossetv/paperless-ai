import { render, screen } from '@testing-library/react';
import type { QueryPlan, SearchStats } from '../../../api/types';
import { QueryPlanSummary } from './QueryPlanSummary';

const plan: QueryPlan = {
  semantic_queries: ['boiler warranty', 'heating system certificate'],
  keyword_terms: ['boiler', 'warranty'],
  sub_questions: ['When was the boiler installed?'],
};

const stats: SearchStats = {
  llm_calls: 2,
  latency_ms: 1423,
  refined: true,
};

describe('QueryPlanSummary', () => {
  it('renders the number of semantic queries searched', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/2 queries searched/i)).toBeInTheDocument();
  });

  it('renders the number of LLM calls', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    // "2 LLM calls" or similar
    expect(screen.getByText(/llm/i)).toBeInTheDocument();
  });

  it('renders a refined indicator when stats.refined is true', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/refined/i)).toBeInTheDocument();
  });

  it('does not show a refined indicator when stats.refined is false', () => {
    const unrefined = { ...stats, refined: false };
    render(<QueryPlanSummary plan={plan} stats={unrefined} />);
    expect(screen.queryByText(/refined/i)).not.toBeInTheDocument();
  });

  it('renders the latency', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/1423/)).toBeInTheDocument();
  });

  it('renders the sub-questions when present', () => {
    render(<QueryPlanSummary plan={plan} stats={stats} />);
    expect(screen.getByText(/When was the boiler installed/)).toBeInTheDocument();
  });

  it('renders gracefully when there are no sub-questions', () => {
    const simplePlan: QueryPlan = { ...plan, sub_questions: [] };
    render(<QueryPlanSummary plan={simplePlan} stats={stats} />);
    // No crash; the latency and LLM call info still shows
    expect(screen.getByText(/llm/i)).toBeInTheDocument();
  });
});
