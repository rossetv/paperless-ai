import type { Meta, StoryObj } from '@storybook/react';
import { SettingsSelectField } from './SettingsSelectField';

const meta = {
  title: 'Primitives/SettingsSelectField',
  component: SettingsSelectField,
  tags: ['autodocs'],
} satisfies Meta<typeof SettingsSelectField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Models: Story = {
  args: {
    id: 'planner',
    label: 'Planner model',
    value: 'gpt-5.4-mini',
    onChange: () => {},
    options: [
      { value: 'gpt-5.4-mini', label: 'gpt-5.4-mini' },
      { value: 'gpt-5.4', label: 'gpt-5.4' },
      { value: 'o4-mini', label: 'o4-mini' },
    ],
  },
};

export const Disabled: Story = {
  args: { ...Models.args, disabled: true },
};
