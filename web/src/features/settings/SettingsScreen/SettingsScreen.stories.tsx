import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsScreen } from './SettingsScreen';

/**
 * The Settings screen story.
 *
 * The screen fetches `/api/settings` on mount. Storybook has no backend, so
 * this story shows the screen's loading / error placeholders — the populated
 * screen is exercised by `SettingsScreen.test.tsx`, which mocks fetch. The
 * individual controls each have their own populated stories.
 */
const meta = {
  title: 'Features/Settings/SettingsScreen',
  component: SettingsScreen,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/settings']}>
          <Story />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof SettingsScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
