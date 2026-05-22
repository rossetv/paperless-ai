import React from 'react';
import { Disclosure } from '../../../components/primitives/Disclosure/Disclosure';
import { Badge } from '../../../components/primitives/Badge/Badge';
import { Text } from '../../../components/primitives/Text/Text';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Stack } from '../../../components/layout/Stack/Stack';
import { Grid } from '../../../components/layout/Grid/Grid';
import type { QueryPlan, SearchStats } from '../../../api/types';

export interface QueryPlanSummaryProps {
  /** The query plan produced by the search pipeline. */
  plan: QueryPlan;
  /** Execution statistics for the search. */
  stats: SearchStats;
}

/**
 * Collapsible "how this answer was built" transparency panel.
 *
 * Composes the `Disclosure` primitive: the summary row carries the headline
 * plus a read-out (query count · LLM calls · latency · a "refined" marker
 * when the pipeline ran a refinement pass); the body lists the semantic
 * queries and the keyword terms in two columns.
 *
 * Composed from: Disclosure, Badge, Text, Chip, Stack, Grid. No own CSS
 * module (§12.5 — features layer is composition-only).
 */
export function QueryPlanSummary({
  plan,
  stats,
}: QueryPlanSummaryProps): React.ReactElement {
  const queryCount = plan.semantic_queries.length;
  const latencySeconds = (stats.latency_ms / 1000).toFixed(2);

  const summary = (
    <Stack direction="horizontal" gap={6} align="center" wrap>
      <Text as="span" variant="caption-bold">
        How this answer was built
      </Text>
      <Badge variant="neutral">
        {queryCount} {queryCount === 1 ? 'query' : 'queries'}
      </Badge>
      <Badge variant="neutral">
        {stats.llm_calls} LLM {stats.llm_calls === 1 ? 'call' : 'calls'}
      </Badge>
      <Badge variant="neutral">{latencySeconds}s</Badge>
      {stats.refined && <Badge variant="accent">refined</Badge>}
    </Stack>
  );

  return (
    <Disclosure summary={summary} defaultOpen>
      <Grid columns={2} gap={8}>
        {/* Semantic queries — a numbered list */}
        <Stack direction="vertical" gap={3}>
          <Text as="span" variant="micro" tone="tertiary">
            Semantic queries
          </Text>
          <ol>
            {plan.semantic_queries.map((query, i) => (
              <li key={i}>
                <Text as="span" variant="caption">
                  {query}
                </Text>
              </li>
            ))}
          </ol>
        </Stack>

        {/* Keyword terms — chips */}
        <Stack direction="vertical" gap={3}>
          <Text as="span" variant="micro" tone="tertiary">
            Keyword terms
          </Text>
          <Stack direction="horizontal" gap={3} wrap>
            {plan.keyword_terms.map((term, i) => (
              <Chip key={i}>{term}</Chip>
            ))}
          </Stack>
        </Stack>
      </Grid>
    </Disclosure>
  );
}
