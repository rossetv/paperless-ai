import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsScreen } from './SettingsScreen';

/**
 * Storybook has no backend, so this shows only the loading / error placeholders; the populated
 * screen is covered by `SettingsScreen.test.tsx`.
 */
const meta = {
  title: 'Features/Settings/SettingsScreen',
  component: SettingsScreen,
  parameters: { layout: 'fullscreen', initialRoute: '/settings' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <Story />
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof SettingsScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
