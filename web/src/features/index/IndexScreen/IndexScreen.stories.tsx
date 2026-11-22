import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { IndexScreen } from './IndexScreen';

/** Storybook stubs no backend, so the queries settle into their empty/error states. */
const meta = {
  title: 'Features/Index/IndexScreen',
  component: IndexScreen,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <div style={{ background: 'var(--colour-bg)', minHeight: '100vh' }}>
          <Story />
        </div>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof IndexScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The dashboard shell — queries resolve to their empty states. */
export const Default: Story = {};
