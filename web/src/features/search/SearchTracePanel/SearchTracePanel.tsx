import React from 'react';
import { Disclosure } from '../../../components/primitives/Disclosure/Disclosure';
import { Text } from '../../../components/primitives/Text/Text';
import { Stack } from '../../../components/layout/Stack/Stack';
import { PipelineStages } from '../../../components/primitives/PipelineStages/PipelineStages';
import type { CostSummary, PhaseRecord } from '../../../api/types';
import { formatSummaryCostLabel, phaseToStages } from '../trace/phaseStages';
import styles from './SearchTracePanel.module.css';

export interface SearchTracePanelProps {
  /** In order; on the error path, the partial phases captured before the failure. */
  phases: PhaseRecord[];
  /** Omitted on the error path, where no honest total exists. */
  cost?: CostSummary;
  /** Opens a judged document; when omitted, verdict rows have no View control. */
  onPreview?: (documentId: number) => void;
}

/**
 * "How this answer was found": the folded trace of every pipeline phase, using
 * the same phase-to-stage mapping as the live loading rail. Renders nothing for
 * an empty trace (a clarify that short-circuits before retrieval).
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
    <div className={styles['panel']}>
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
    </div>
  );
}
