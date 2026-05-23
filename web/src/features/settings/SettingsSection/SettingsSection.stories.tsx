import type { Meta, StoryObj } from '@storybook/react';
import { SettingsSection } from './SettingsSection';
import { SETTINGS_SECTIONS } from '../fieldModel';

const meta = {
  title: 'Features/Settings/SettingsSection',
  component: SettingsSection,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsSection>;

export default meta;
type Story = StoryObj<typeof meta>;

const SEARCH = SETTINGS_SECTIONS.find((s) => s.id === 'search')!;

export const SearchServer: Story = {
  args: {
    section: SEARCH,
    onChange: () => {},
    values: {
      SEARCH_TOP_K: 10,
      SEARCH_MAX_REFINEMENTS: 1,
      SEARCH_PLANNER_MODEL: 'gpt-5.4-mini',
      SEARCH_ANSWER_MODEL: 'gpt-5.4',
      SEARCH_MAX_CONCURRENT: 4,
      SEARCH_SESSION_TTL: 604800,
      SEARCH_SERVER_HOST: '0.0.0.0',
      SEARCH_SERVER_PORT: 8080,
    },
  },
};
