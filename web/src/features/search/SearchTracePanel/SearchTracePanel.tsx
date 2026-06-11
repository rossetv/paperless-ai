import React from 'react';
import { Disclosure } from '../../../components/primitives/Disclosure/Disclosure';
import { Text } from '../../../components/primitives/Text/Text';
import { Stack } from '../../../components/layout/Stack/Stack';
import { PipelineStages } from '../../../components/primitives/PipelineStages/PipelineStages';
import type { CostSummary, PhaseRecord } from '../../../api/types';
import { formatSummaryCostLabel, phaseToStages } from '../trace/phaseStages';
import styles from './SearchTracePanel.module.css';

export interface SearchTracePanelProps {
  /**
   * The phases to display, in order. The success path passes
   * `result.trace.phases`; the error path passes the partial `phaseRecords`
   * captured before the stream failed, so the trace still shows what ran.
   */
  phases: PhaseRecord[];
  /**
   * The whole-query cost summary — rendered as a compact chip in the summary
   * row. Omitted on the error path (no honest total was produced).
   */
  cost?: CostSummary;
  /**
   * Called with a document id when a judged document's "Preview" control is
   * activated. Threaded straight to `PipelineStages`; when omitted, the judge
   * verdict rows render without a Preview control. The page supplies the same
   * `onPreview` handler the source cards use, so preview opens the in-app
   * document viewer.
   */
  onPreview?: (documentId: number) => void;
}

/**
 * "How this answer was found" — the folded reasoning-trace disclosure.
 *
 * A collapsed `Disclosure` whose summary carries the headline and a compact
 * whole-query token/cost chip. Opened, it lists every pipeline phase using the
 * same `PipelineStages` rendering as the live loading rail (all rows in the
 * `done` state), including the planner's rewritten query, retrieval counts, the
 * vector-gate outcome, the judge's per-document rationales, and a per-phase
 * cost chip. The phase→stage mapping is shared with `LoadingScreen` via
 * `trace/phaseStages`, so the live rail and the folded trace never diverge.
 *
 * Renders nothing when there are no phases (a Layer-1 clarify short-circuit
 * produces an empty trace) — an empty disclosure would be noise.
 *
 * Composed from: Disclosure, PipelineStages, Text, Stack.
 * Own CSS module provides the summary-row layout (tokens only, §12.5).
 */
export function SearchTracePanel({
  phases,
  cost,
  onPreview,
}: SearchTracePanelProps): React.ReactElement | null {
  if (phases.length === 0) {
    return null;
  }

  const costLabel =
    cost !== undefined ? formatSummaryCostLabel(cost) : undefined;
  const stages = phaseToStages(phases, null);

  const summary = (
    <span className={styles['summary']}>
      <Text as="span" variant="caption-bold">
        How this answer was found
      </Text>
      {costLabel !== undefined && (
        <span className={styles['cost']}>{costLabel}</span>
      )}
    </span>
  );

  return (
    <Disclosure summary={summary}>
      <Stack direction="vertical" gap={3}>
        <Text as="span" variant="micro" tone="tertiary">
          Each step of the agentic pipeline, with its token and dollar cost.
        </Text>
        <PipelineStages
          collapsible
          stages={stages}
          {...(onPreview !== undefined ? { onPreviewDocument: onPreview } : {})}
        />
      </Stack>
    </Disclosure>
  );
}
