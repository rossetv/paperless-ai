import React from 'react';
import type { Preview } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// Icon fonts, as main.tsx loads them; without them icons render blank.
import '@fortawesome/fontawesome-free/css/fontawesome.min.css';
import '@fortawesome/fontawesome-free/css/solid.min.css';
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
  // Router render without throwing. Stories must not add a router of their own;
  // set the `initialRoute` parameter instead.
  decorators: [
    (Story, { parameters }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[parameters.initialRoute ?? '/']}>
          <Story />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  ],
};

export default preview;
