import type { Meta, StoryObj } from '@storybook/react';
import { QueryPlanSummary } from './QueryPlanSummary';

const meta = {
  title: 'Features/Search/QueryPlanSummary',
  component: QueryPlanSummary,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof QueryPlanSummary>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Refined: Story = {
  args: {
    plan: {
      semantic_queries: [
        'Total annual energy payments to Npower in 2024',
        'Direct debit schedule and upcoming collection date',
        'Tariff changes and price-cap revisions',
      ],
      keyword_terms: ['Npower', 'direct debit', '2024', 'price cap', 'Ofgem'],
      sub_questions: [],
    },
    stats: { llm_calls: 3, latency_ms: 1842, refined: true },
  },
};

export const NotRefined: Story = {
  args: {
    plan: {
      semantic_queries: ['Single semantic query'],
      keyword_terms: ['invoice'],
      sub_questions: [],
    },
    stats: { llm_calls: 1, latency_ms: 640, refined: false },
  },
};
