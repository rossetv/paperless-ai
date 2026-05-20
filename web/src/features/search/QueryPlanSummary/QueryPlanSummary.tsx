import React from 'react';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Stack } from '../../../components/layout/Stack/Stack';
import type { QueryPlan, SearchStats } from '../../../api/types';

export interface QueryPlanSummaryProps {
  /** The query plan produced by the search pipeline. */
  plan: QueryPlan;
  /** Execution statistics for the search. */
  stats: SearchStats;
}

/**
 * Compact transparency line showing how the search was executed.
 *
 * Surfaces: number of semantic queries, keyword terms, LLM call count,
 * latency, whether the answer was refined, and any sub-questions raised.
 *
 * The purpose is to give power users confidence in the results and signal
 * when the pipeline took extra steps (refinement) or extra time.
 *
 * Composed from: Badge, Icon, Stack.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function QueryPlanSummary({ plan, stats }: QueryPlanSummaryProps): React.ReactElement {
  const queryCount = plan.semantic_queries.length;

  return (
    <Stack direction="vertical" gap={4}>
      {/* Primary stats line */}
      <Stack direction="horizontal" gap={4} align="center" wrap>
        <Icon name="info" size="small" label="Query plan" />

        <Badge variant="neutral">
          {queryCount} {queryCount === 1 ? 'query' : 'queries'} searched
        </Badge>

        <Badge variant="neutral">
          {stats.llm_calls} LLM {stats.llm_calls === 1 ? 'call' : 'calls'}
        </Badge>

        <Badge variant="neutral">
          {stats.latency_ms} ms
        </Badge>

        {stats.refined && (
          <Badge variant="accent">refined</Badge>
        )}
      </Stack>

      {/* Sub-questions raised by the planner */}
      {plan.sub_questions.length > 0 && (
        <Stack direction="vertical" gap={2}>
          {plan.sub_questions.map((q, i) => (
            <span key={i}>{q}</span>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
