import React from 'react';
import type { Preview } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

// Tokens, themes and resets; without them stories using var(--…) render unstyled.
import '../src/styles/global.css';

// No retries: Storybook has no backend, so query hooks should settle on their
// error or empty state at once.
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
  // The app's root providers, so components using TanStack Query or React
  // Router render without throwing.
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
