import type { Meta, StoryObj } from '@storybook/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { IndexScreen } from './IndexScreen';

/** Storybook stubs no backend, so the queries settle into their empty/error states. */
const meta = {
  title: 'Features/Index/IndexScreen',
  component: IndexScreen,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <div style={{ background: 'var(--colour-bg)', minHeight: '100vh' }}>
            <Story />
          </div>
        </MemoryRouter>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof IndexScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The dashboard shell — queries resolve to their empty states. */
export const Default: Story = {};
