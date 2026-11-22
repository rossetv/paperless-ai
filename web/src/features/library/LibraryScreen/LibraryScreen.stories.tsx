import React from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LibraryScreen } from './LibraryScreen';

/*
 * Storybook has no backend, so the story seeds the `['facets']` cache entry
 * (key from `api/hooks.ts`) and lets the documents query fail.
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

/** Facets seeded; the document list shows its error state. */
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
