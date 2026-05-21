import type { Meta, StoryObj } from '@storybook/react';
import { TextArea } from './TextArea';

const meta = {
  title: 'Primitives/TextArea',
  component: TextArea,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    disabled: { control: 'boolean' },
    required: { control: 'boolean' },
    rows: { control: 'number' },
    error: { control: 'text' },
    placeholder: { control: 'text' },
    label: { control: 'text' },
  },
} satisfies Meta<typeof TextArea>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    id: 'default',
    label: 'Your message',
    placeholder: 'Enter your message here…',
    rows: 4,
  },
};

export const WithError: Story = {
  args: {
    id: 'notes-error',
    label: 'Notes',
    value: '',
    error: 'Notes cannot be empty.',
  },
};

export const Disabled: Story = {
  args: {
    id: 'disabled',
    label: 'Locked field',
    value: 'This content is read-only.',
    disabled: true,
  },
};

export const LargeRows: Story = {
  args: {
    id: 'large',
    label: 'Detailed description',
    placeholder: 'Write a detailed description…',
    rows: 8,
  },
};

export const AllStates: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-14)', width: 'var(--width-empty-state)' }}>
      <TextArea id="normal" label="Normal" placeholder="Enter text…" rows={3} />
      <TextArea id="disabled" label="Disabled" placeholder="Disabled" disabled rows={3} />
      <TextArea
        id="error"
        label="With error"
        value="bad input"
        error="This field is required."
        rows={3}
      />
    </div>
  ),
};
