import React from 'react';
import type { Preview } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

// Pulls in the design system — tokens.css, themes.css, global resets — so every
// story renders with the same design values the app uses. Without this, stories
// that reference var(--…) tokens render unstyled.
import '../src/styles/global.css';

// A QueryClient shared by every story. Retries are disabled so a story whose
// component calls a TanStack Query hook (e.g. FilterControls → useFacets)
// resolves to its error/empty state immediately instead of retrying a request
// that has no backend in Storybook.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        colour: /(colour|color)$/i,
        date: /Date$/i,
      },
    },
  },
  // Global decorators — every story is wrapped in the providers the app
  // supplies at its root, so feature components that depend on TanStack Query
  // or React Router render without throwing (CODE_GUIDELINES §12.8/§12.9).
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Story />
        </BrowserRouter>
      </QueryClientProvider>
    ),
  ],
};

export default preview;
