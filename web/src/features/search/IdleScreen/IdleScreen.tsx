import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Text } from '../../../components/primitives/Text/Text';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { RecentSearchStrip } from '../../../components/primitives/RecentSearchStrip/RecentSearchStrip';
import { IndexStatusFooter } from '../../../components/primitives/IndexStatusFooter/IndexStatusFooter';
import { useRecentSearches, useStats } from '../../../api/hooks';
import { relativeTime } from '../../../lib/relativeTime';
import { QUICK_FILTERS } from '../lib/quickFilters';
import styles from './IdleScreen.module.css';

export interface IdleScreenProps {
  /** Called with a query string when the user starts a search. */
  onSearch: (query: string) => void;
}

/**
 * The search idle screen — the hero.
 *
 * A centred hero: a display headline, the large `SearchField`, a row of
 * quick-filter chips, the recent-searches strip and the index-status footer.
 * Quick-filter chips and recent-search rows both call `onSearch`.
 *
 * Recent searches come from `useRecentSearches`; any error simply omits the
 * strip (the `RecentSearchStrip` primitive renders `null` for an empty list).
 * The status footer is shown only once `useStats` has resolved.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, Text, Chip,
 * RecentSearchStrip, IndexStatusFooter.
 * Own CSS module provides the count-highlight class for the hero subtitle.
 */
export function IdleScreen({ onSearch }: IdleScreenProps): React.ReactElement {
  const recent = useRecentSearches();
  const stats = useStats();

  const recentItems =
    recent.isSuccess && recent.data !== undefined
      ? recent.data.searches.map((entry) => ({
          query: entry.query,
          time: relativeTime(entry.created_at),
        }))
      : [];

  return (
    <SearchScreenLayout variant="centred">
      <Stack direction="vertical" gap={13} align="center">
        <Text as="h1" variant="hero">
          Ask your library.
        </Text>

        {stats.isSuccess && stats.data !== undefined && (
          <Text as="p" variant="body-large" tone="tertiary">
            Semantic + keyword search across{' '}
            <strong className={styles['count-highlight']}>
              {stats.data.document_count.toLocaleString('en-GB')}
            </strong>{' '}
            documents in your Paperless library.
          </Text>
        )}

        <SearchField
          id="idle-search"
          placeholder="What do you want to know?"
          onSubmit={onSearch}
        />

        <Stack direction="horizontal" gap={6} wrap justify="center">
          {QUICK_FILTERS.map((filter) => (
            <Chip key={filter} onClick={() => onSearch(filter)}>
              {filter}
            </Chip>
          ))}
        </Stack>

        <RecentSearchStrip items={recentItems} onSelect={onSearch} />

        {stats.isSuccess && stats.data !== undefined && (
          <IndexStatusFooter
            documentCount={stats.data.document_count}
            chunkCount={stats.data.chunk_count}
            embeddingModel={stats.data.embedding_model}
          />
        )}
      </Stack>
    </SearchScreenLayout>
  );
}
