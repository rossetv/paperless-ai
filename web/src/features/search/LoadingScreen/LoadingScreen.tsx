import React, { useEffect, useState } from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Card } from '../../../components/primitives/Card/Card';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { Text } from '../../../components/primitives/Text/Text';
import { Skeleton } from '../../../components/primitives/Skeleton/Skeleton';
import { PipelineStages } from '../../../components/primitives/PipelineStages/PipelineStages';
import type { PipelineStage } from '../../../components/primitives/PipelineStages/PipelineStages';
import { FilterControls } from '../FilterControls/FilterControls';
import type { FilterRequest } from '../../../api/types';
import styles from './LoadingScreen.module.css';

export interface LoadingScreenProps {
  /** The in-flight query — recapped in the inline search field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
}

/**
 * Build the pipeline-stage rail from the elapsed search time.
 *
 * `POST /api/search` is a single round-trip — the browser cannot observe the
 * server's real stage boundaries — so this is a time-based ESTIMATE, not a
 * measured progress meter. Planning is shown working for the first couple of
 * seconds, then retrieval, then synthesis (the long tail, where most of a
 * search's wall-clock goes). It exists so the rail visibly advances instead of
 * sitting frozen on a hard-coded snapshot; the counter beside it shows the real
 * measured elapsed time. A truly live rail would need the server to stream
 * per-stage events, which the single-round-trip API does not.
 */
function pipelineStages(elapsedSeconds: number): PipelineStage[] {
  const planningDone = elapsedSeconds >= 2;
  const retrievingDone = elapsedSeconds >= 5;
  return [
    {
      label: 'Planning the query',
      detail: 'Semantic queries and keyword terms',
      state: planningDone ? 'done' : 'active',
    },
    {
      label: 'Embedding & retrieving',
      detail: 'Vector + keyword search, RRF fusion',
      state: !planningDone ? 'pending' : retrievingDone ? 'done' : 'active',
    },
    {
      label: 'Synthesising the answer',
      detail: 'Final answer with citations',
      state: retrievingDone ? 'active' : 'pending',
    },
  ];
}

/**
 * The search loading screen.
 *
 * The rail+content layout: the filter rail, then a recap of the query, a card
 * carrying the spinner, a live elapsed counter and the `PipelineStages` rail,
 * and two skeleton source placeholders. The counter ticks the real measured
 * elapsed time; the rail advances on a time estimate (see `pipelineStages`) —
 * the search request is a single round-trip, so true per-stage progress is not
 * observable from the browser.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, Card, Spinner, Text,
 * Skeleton, PipelineStages, FilterControls.
 * Own CSS module provides the spacer class used in the spinner row.
 */
export function LoadingScreen({
  query,
  filters,
  onFiltersChange,
}: LoadingScreenProps): React.ReactElement {
  // Real elapsed seconds since this screen mounted — drives the visible counter
  // and the estimated stage progression. The interval is cleared on unmount,
  // which happens as soon as the search resolves and results replace this view.
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(id);
  }, []);

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
            <PipelineStages stages={pipelineStages(elapsedSeconds)} />
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
