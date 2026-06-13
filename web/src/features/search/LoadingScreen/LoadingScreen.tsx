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
import { formatCostLabel, formatElapsed, phaseToStages } from '../trace/phaseStages';
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
   * Called with a document id when a judged document's "View" control is
   * activated. The page supplies the same `onPreview` handler the source cards
   * use, so it opens the in-app document viewer. The lean live rail no longer
   * shows verdict rows, so this is currently unused there, but is threaded for
   * parity with the folded trace.
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
 * token/cost chip — not a time-based estimate. The elapsed counter is computed
 * from a real wall-clock start timestamp (`now - startedAt`) on every render,
 * formatted mm:ss, so it tracks true elapsed time rather than ticking ahead.
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
  // Real elapsed time since this screen first rendered — the single source of
  // truth is the wall-clock `startedAt`, captured once in a ref (so it survives
  // re-renders and never resets). Each render recomputes `now - startedAt`; a
  // 500 ms interval only forces those re-renders. This drives the counter from
  // true wall-clock, not per-frame/per-phase increments that ran ~2× fast.
  const startedAtRef = useRef<number>(Date.now());
  const [, forceTick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const id = window.setInterval(forceTick, 500);
    return () => window.clearInterval(id);
  }, []);
  const elapsedLabel = formatElapsed(Date.now() - startedAtRef.current);

  const stages = phaseToStages(phaseRecords, activePhase);

  // Cumulative spend so far — summed across every completed phase. Shown as a
  // single live counter in the header so the user sees the running cost without
  // the per-phase chips that the lean rail omits.
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
            {/* Spinner row: icon, heading, spacer, live elapsed + cost counters.
                The two live counters share one polite status region so screen
                readers hear the running progress without interruption (FE-30). */}
            <Stack direction="horizontal" gap={9} align="center">
              <Spinner size="small" label="Searching" />
              <Text as="span" variant="body-emphasis">
                Searching your library…
              </Text>
              <span className={styles['spacer']} />
              <span role="status" aria-live="polite" aria-atomic="true">
                <Text as="span" variant="micro" tone="tertiary">
                  {elapsedLabel}
                  {costCounter !== undefined && ` · ${costCounter}`}
                </Text>
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
