import React, { useEffect, useState } from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Card } from '../../../components/primitives/Card/Card';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { Text } from '../../../components/primitives/Text/Text';
import { Skeleton } from '../../../components/primitives/Skeleton/Skeleton';
import { PipelineStages } from '../../../components/primitives/PipelineStages/PipelineStages';
import { FilterControls } from '../FilterControls/FilterControls';
import { phaseToStages } from '../trace/phaseStages';
import type { FilterRequest, PhaseRecord, SearchPhase } from '../../../api/types';
import styles from './LoadingScreen.module.css';

export interface LoadingScreenProps {
  /** The in-flight query — recapped in the inline search field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
  /**
   * The phases the stream has completed so far, in order. Each becomes a
   * `done` rail row with its rewritten query / counts / verdicts and a cost
   * chip. Empty until the first `phase_done` lands.
   */
  phaseRecords: PhaseRecord[];
  /** The phase currently running — shown as the "in progress" rail row. */
  activePhase: SearchPhase | null;
  /**
   * Called with a document id when a judged document's "Preview" control is
   * activated in the live rail. The page supplies the same `onPreview` handler
   * the source cards use, so preview opens the in-app document viewer. When
   * omitted, the judge verdict rows render without a Preview control.
   */
  onPreview?: (documentId: number) => void;
}

/**
 * The search loading screen — a LIVE pipeline rail.
 *
 * The rail+content layout: the filter rail, then a recap of the query, a card
 * carrying the spinner, a real elapsed counter and the `PipelineStages` rail,
 * and two skeleton source placeholders. The rail now renders the REAL phases
 * streamed from `POST /api/search/stream` (planner rewrite, retrieval counts,
 * vector-gate outcome, per-document judge verdicts, synthesis), each with a
 * token/cost chip — not a time-based estimate. The counter still ticks the
 * measured wall-clock since the screen mounted.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, Card, Spinner, Text,
 * Skeleton, PipelineStages, FilterControls; the phase→stage mapping lives in
 * `trace/phaseStages` (shared with `SearchTracePanel`).
 * Own CSS module provides the spacer class used in the spinner row.
 */
export function LoadingScreen({
  query,
  filters,
  onFiltersChange,
  phaseRecords,
  activePhase,
  onPreview,
}: LoadingScreenProps): React.ReactElement {
  // Real elapsed seconds since this screen mounted — drives the visible
  // counter. The interval is cleared on unmount, which happens as soon as the
  // search resolves and results replace this view.
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(id);
  }, []);

  const stages = phaseToStages(phaseRecords, activePhase);

  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Query recap — a read-only inline search field. */}
        <SearchField
          id="loading-search"
          value={query}
          disabled
          onSubmit={() => {}}
        />

        {/* Pipeline progress card. */}
        <Card elevated>
          <Stack direction="vertical" gap={10}>
            {/* Spinner row: icon, heading, spacer, live elapsed counter. */}
            <Stack direction="horizontal" gap={9} align="center">
              <Spinner size="small" label="Searching" />
              <Text as="span" variant="body-emphasis">
                Searching your library…
              </Text>
              <span className={styles['spacer']} />
              <Text as="span" variant="micro" tone="tertiary">
                {elapsedSeconds}s
              </Text>
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

        {/* Skeleton source placeholders. */}
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
