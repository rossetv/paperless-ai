import React from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LibraryScreen } from './LibraryScreen';

/*
 * LibraryScreen drives `useDocuments` and `useFacets`. Storybook has no
 * backend, so each story supplies its own QueryClient seeded with the cache
 * entries those hooks read. The query keys mirror `api/hooks.ts`:
 *   useFacets    → ['facets']
 *   useDocuments → ['documents', query]
 * Seeding `['facets']` and leaving documents to resolve to its error state
 * keeps the story self-contained.
 */
function withSeededClient(facets: unknown): React.FC<{ children: React.ReactNode }> {
  return function Provider({ children }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(['facets'], facets);
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const FACETS = {
  correspondents: [{ kind: 'correspondent', id: 1, name: 'Npower Energy' }],
  document_types: [{ kind: 'document_type', id: 1, name: 'Statement' }],
  tags: [{ kind: 'tag', id: 1, name: 'Energy' }],
  earliest: '2024-01-01',
  latest: '2025-12-31',
};

const meta = {
  title: 'Features/Library/LibraryScreen',
  component: LibraryScreen,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof LibraryScreen>;

export default meta;

type Story = StoryObj<typeof meta>;

/**
 * The screen with facets seeded. `useDocuments` has no seeded data and
 * `retry` is off, so the document list resolves to its error state — the
 * story exercises the header, search field, rail and error block.
 */
export const Default: Story = {
  decorators: [
    (StoryFn) => {
      const Provider = withSeededClient(FACETS);
      return (
        <Provider>
          <StoryFn />
        </Provider>
      );
    },
  ],
};
