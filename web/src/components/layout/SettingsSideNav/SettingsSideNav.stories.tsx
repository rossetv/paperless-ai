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
    groups: [
      {
        title: 'Access Control',
        items: [
          { id: 'users', label: 'Users', to: '/settings/users' },
          { id: 'keys', label: 'API Keys', to: '/settings/keys' },
        ],
      },
    ],
  },
};

export const WithConfigurationGroup: Story = {
  args: {
    groups: [
      {
        title: 'Configuration',
        items: [
          { id: 'llm', label: 'LLM Provider', to: '/settings/llm' },
          { id: 'search', label: 'Search Server', to: '/settings/search' },
        ],
      },
      {
        title: 'Access Control',
        items: [
          { id: 'users', label: 'Users', to: '/settings/users' },
          { id: 'keys', label: 'API Keys', to: '/settings/keys' },
        ],
      },
    ],
  },
};
