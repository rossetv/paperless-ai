import type { Meta, StoryObj } from '@storybook/react';
import { Input } from './Input';

const meta = {
  title: 'Primitives/Input',
  component: Input,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    type: {
      control: 'select',
      options: ['text', 'email', 'password', 'search', 'tel', 'url', 'number'],
    },
    disabled: { control: 'boolean' },
    required: { control: 'boolean' },
    error: { control: 'text' },
    placeholder: { control: 'text' },
    label: { control: 'text' },
  },
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    id: 'default',
    label: 'Search',
    placeholder: 'Search documents…',
  },
};

export const WithError: Story = {
  args: {
    id: 'email',
    label: 'Email address',
    type: 'email',
    value: 'not-an-email',
    error: 'Please enter a valid email address.',
  },
};

export const Disabled: Story = {
  args: {
    id: 'disabled',
    label: 'Unavailable',
    placeholder: 'Not available right now',
    disabled: true,
  },
};

export const WithoutLabel: Story = {
  args: {
    id: 'no-label',
    placeholder: 'Search…',
  },
};

export const AllStates: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-14)', width: 'var(--width-empty-state)' }}>
      <Input id="normal" label="Normal" placeholder="Enter text…" />
      <Input id="disabled" label="Disabled" placeholder="Disabled" disabled />
      <Input id="error" label="With error" value="bad" error="This field is required." />
    </div>
  ),
};
