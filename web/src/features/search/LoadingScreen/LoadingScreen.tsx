import React from 'react';
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

export interface LoadingScreenProps {
  /** The in-flight query — recapped in the inline search field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
}

/**
 * The agentic-search pipeline stages, fixed for the in-flight view.
 *
 * `POST /api/search` is a single round-trip — the browser cannot observe the
 * server's progress — so the rail shows a representative snapshot: planning
 * done, retrieval in progress, synthesis pending. It is an "in-flight"
 * affordance, not a live progress meter.
 */
const PIPELINE_STAGES: readonly PipelineStage[] = [
  {
    label: 'Planning the query',
    detail: 'Semantic queries and keyword terms',
    state: 'done',
  },
  {
    label: 'Embedding & retrieving',
    detail: 'Vector + keyword search, RRF fusion',
    state: 'active',
  },
  {
    label: 'Synthesising the answer',
    detail: 'Final answer with citations',
    state: 'pending',
  },
];

/**
 * The search loading screen.
 *
 * The rail+content layout: the filter rail, then a recap of the query, a card
 * carrying the spinner and the `PipelineStages` rail, and two skeleton source
 * placeholders. The pipeline rail is a fixed in-flight snapshot — the search
 * request is a single round-trip, so live stage progress is not observable.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, Card, Spinner, Text,
 * Skeleton, PipelineStages, FilterControls. No own CSS module (§12.5 —
 * features layer is composition-only).
 */
export function LoadingScreen({
  query,
  filters,
  onFiltersChange,
}: LoadingScreenProps): React.ReactElement {
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
            <Stack direction="horizontal" gap={6} align="center">
              <Spinner size="small" label="Searching" />
              <Text as="span" variant="body-emphasis">
                Searching your library…
              </Text>
            </Stack>
            <PipelineStages stages={[...PIPELINE_STAGES]} />
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
