import type { Meta, StoryObj } from '@storybook/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsSideNav } from './SettingsSideNav';

const meta = {
  title: 'Layout/SettingsSideNav',
  component: SettingsSideNav,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/settings/users']}>
        <Story />
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof SettingsSideNav>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AccessControl: Story = {
  args: {
    eyebrow: 'Settings',
    groups: [
      {
        title: 'Access Control',
        items: [
          { id: 'users', label: 'Users', to: '/settings/users', icon: 'users' },
          { id: 'keys', label: 'API Keys', to: '/settings/keys', icon: 'key' },
        ],
      },
    ],
  },
};

export const WithConfigurationGroup: Story = {
  args: {
    eyebrow: 'Settings',
    groups: [
      {
        title: 'Configuration',
        items: [
          { id: 'llm', label: 'LLM Provider', to: '/settings#llm', icon: 'sparkle' },
          { id: 'search', label: 'Search Server', to: '/settings#search', icon: 'search' },
        ],
      },
      {
        title: 'Access Control',
        items: [
          { id: 'users', label: 'Users', to: '/settings/users', icon: 'users' },
          { id: 'keys', label: 'API Keys', to: '/settings/keys', icon: 'key' },
        ],
      },
    ],
  },
};
