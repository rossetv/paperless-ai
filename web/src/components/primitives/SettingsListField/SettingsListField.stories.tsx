import type { Meta, StoryObj } from '@storybook/react';
import { SettingsListField } from './SettingsListField';

const meta = {
  title: 'Primitives/SettingsListField',
  component: SettingsListField,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsListField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
  args: {
    id: 'models',
    label: 'Model fallback chain',
    value: [],
    onChange: () => {},
    placeholder: 'Add a model identifier…',
  },
};

export const WithItems: Story = {
  args: {
    id: 'models',
    label: 'Model fallback chain',
    value: ['gpt-5.4-mini', 'gpt-5.4', 'o4-mini'],
    onChange: () => {},
    placeholder: 'Add a model identifier…',
  },
};

export const Disabled: Story = {
  args: {
    id: 'models',
    label: 'Model fallback chain',
    value: ['gpt-5.4-mini', 'gpt-5.4'],
    onChange: () => {},
    disabled: true,
  },
};
