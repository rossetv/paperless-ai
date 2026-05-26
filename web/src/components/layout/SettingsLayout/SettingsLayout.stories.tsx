import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsLayout } from './SettingsLayout';

const meta = {
  title: 'Layout/SettingsLayout',
  component: SettingsLayout,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/settings/users']}>
        <Story />
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof SettingsLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    title: 'Users',
    subtitle: 'Anyone with a username and password who can sign in to the web UI.',
    children: (
      <div
        style={{
          padding: 'var(--spacing-14)',
          background: 'var(--colour-surface)',
          borderRadius: 'var(--radius-large)',
          border: '1px solid var(--colour-border)',
        }}
      >
        Page body goes here.
      </div>
    ),
  },
};
