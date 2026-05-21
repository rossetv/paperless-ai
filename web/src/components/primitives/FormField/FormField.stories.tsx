import type { Meta, StoryObj } from '@storybook/react';
import { FormField } from './FormField';

const meta = {
  title: 'Primitives/FormField',
  component: FormField,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof FormField>;

export default meta;
type Story = StoryObj<typeof meta>;

// A bare native input stands in for a real control so the story shows the
// scaffolding (label + error wiring) in isolation.
export const WithLabel: Story = {
  args: {
    id: 'field-demo',
    label: 'Email address',
    children: ({ errorId, hasError }) => (
      <input
        id="field-demo"
        type="email"
        aria-invalid={hasError ? 'true' : undefined}
        aria-describedby={errorId}
      />
    ),
  },
};

export const WithError: Story = {
  args: {
    id: 'field-error',
    label: 'Email address',
    error: 'Enter a valid email address',
    children: ({ errorId, hasError }) => (
      <input
        id="field-error"
        type="email"
        aria-invalid={hasError ? 'true' : undefined}
        aria-describedby={errorId}
      />
    ),
  },
};
