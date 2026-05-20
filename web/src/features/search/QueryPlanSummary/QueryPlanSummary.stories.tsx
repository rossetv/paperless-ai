import type { Meta, StoryObj } from '@storybook/react';
import type { QueryPlan, SearchStats } from '../../../api/types';
import { QueryPlanSummary } from './QueryPlanSummary';

const basePlan: QueryPlan = {
  semantic_queries: ['boiler warranty certificate'],
  keyword_terms: ['boiler', 'warranty'],
  sub_questions: [],
};

const refinedPlan: QueryPlan = {
  semantic_queries: [
    'boiler warranty certificate',
    'central heating installation guarantee',
  ],
  keyword_terms: ['boiler', 'warranty', 'heating'],
  sub_questions: [
    'What is the boiler model number?',
    'When was the boiler installed?',
  ],
};

const baseStats: SearchStats = {
  llm_calls: 1,
  latency_ms: 342,
  refined: false,
};

const refinedStats: SearchStats = {
  llm_calls: 3,
  latency_ms: 1087,
  refined: true,
};

const meta = {
  title: 'Features/Search/QueryPlanSummary',
  component: QueryPlanSummary,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof QueryPlanSummary>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Simple single-query plan, no refinement. */
export const Simple: Story = {
  args: {
    plan: basePlan,
    stats: baseStats,
  },
};

/** Refined plan — multiple semantic queries, sub-questions, refined badge shown. */
export const Refined: Story = {
  args: {
    plan: refinedPlan,
    stats: refinedStats,
  },
};
