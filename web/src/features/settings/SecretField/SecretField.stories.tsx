import type { Meta, StoryObj } from '@storybook/react';
import { SecretField } from './SecretField';

const meta = {
  title: 'Features/Settings/SecretField',
  component: SecretField,
  tags: ['autodocs'],
} satisfies Meta<typeof SecretField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Masked: Story = {
  args: {
    id: 'token',
    label: 'API token',
    maskedValue: '••••••••••••••••••••••3f9b',
    onChange: () => {},
  },
};
