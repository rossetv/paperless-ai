import React, { useEffect, useRef, useReducer } from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Card } from '../../../components/primitives/Card/Card';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { Text } from '../../../components/primitives/Text/Text';
import { Skeleton } from '../../../components/primitives/Skeleton/Skeleton';
import { PipelineStages } from '../../../components/primitives/PipelineStages/PipelineStages';
import { FilterControls } from '../../../components/patterns/FilterControls/FilterControls';
import {
  formatCostLabel,
  formatElapsed,
  phaseToStages,
} from '../trace/phaseStages';
import type {
  FilterRequest,
  PhaseRecord,
  SearchPhase,
} from '../../../api/types';
import styles from './LoadingScreen.module.css';

export interface LoadingScreenProps {
  query: string;
  filters: FilterRequest;
  onFiltersChange: (filters: FilterRequest) => void;
  /** Completed phases in order; empty until the first `phase_done`. */
  phaseRecords: PhaseRecord[];
  /** The running phase, shown as the "in progress" row. */
  activePhase: SearchPhase | null;
  /**
   * Opens a judged document in the viewer. The live rail shows no verdict
   * rows, so it is only passed through for parity with the folded trace.
   */
  onPreview?: (documentId: number) => void;
}

/**
 * The search loading screen: a live rail of the phases streamed from
 * `POST /api/search/stream`, with an elapsed counter and running cost.
 */
export function LoadingScreen({
  query,
  filters,
  onFiltersChange,
  phaseRecords,
  activePhase,
  onPreview,
}: LoadingScreenProps): React.ReactElement {
  // Elapsed time is recomputed from a wall-clock start on every render; the
  // interval only forces re-renders. Counting ticks instead would drift.
  const startedAtRef = useRef<number>(Date.now());
  const [, forceTick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const id = window.setInterval(forceTick, 500);
    return () => window.clearInterval(id);
  }, []);
  const elapsedLabel = formatElapsed(Date.now() - startedAtRef.current);

  const stages = phaseToStages(phaseRecords, activePhase);
  const activeStage = stages.find((s) => s.state === 'active');

  // The live rail omits per-phase cost chips, so the header shows the running total.
  const spent = phaseRecords.reduce(
    (acc, r) => ({
      tokens: acc.tokens + (r.tokens?.total ?? 0),
      usd: acc.usd + (r.cost?.usd ?? 0),
    }),
    { tokens: 0, usd: 0 },
  );
  const costCounter =
    spent.tokens > 0
      ? formatCostLabel(
          { prompt: 0, completion: 0, reasoning: 0, total: spent.tokens },
          { usd: spent.usd, local: false },
        )
      : undefined;

  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Read-only query recap */}
        <SearchField
          id="loading-search"
          value={query}
          disabled
          onSubmit={() => {}}
        />

        {/* Pipeline progress */}
        <Card elevated>
          <Stack direction="vertical" gap={10}>
            {/* Only the phase is announced; the timer ticks every 500 ms and
                would be re-read constantly. */}
            <Stack direction="horizontal" gap={9} align="center">
              <Spinner size="small" label="Searching" />
              <Text as="span" variant="body-emphasis">
                Searching your library…
              </Text>
              <span className={styles['spacer']} />
              {/* A plain wrapper keeps the row's line-box height. */}
              <span>
                <Text as="span" variant="micro" tone="tertiary">
                  {elapsedLabel}
                  {costCounter !== undefined && ` · ${costCounter}`}
                </Text>
              </span>
              <span
                role="status"
                aria-live="polite"
                aria-atomic="true"
                className="visually-hidden"
              >
                {activeStage?.label}
              </span>
            </Stack>
            {stages.length > 0 && (
              <PipelineStages
                stages={stages}
                {...(onPreview !== undefined
                  ? { onPreviewDocument: onPreview }
                  : {})}
              />
            )}
          </Stack>
        </Card>

        {/* Skeleton sources */}
        {[0, 1].map((i) => (
          <Card key={i}>
            <Stack direction="vertical" gap={4}>
              <Skeleton variant="text" width="wide" />
              <Skeleton variant="text" lines={3} />
            </Stack>
          </Card>
        ))}
      </Stack>
    </SearchScreenLayout>
  );
}
