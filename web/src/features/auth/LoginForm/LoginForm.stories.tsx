import type { Meta, StoryObj } from '@storybook/react';
import { LoginForm } from './LoginForm';

const meta = {
  title: 'Features/Auth/LoginForm',
  component: LoginForm,
  parameters: { layout: 'centered' },
  args: {
    onSuccess: () => undefined,
  },
} satisfies Meta<typeof LoginForm>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Default idle state — user has not yet entered anything. */
export const Idle: Story = {};

/**
 * Error state — shown when the user submits an incorrect key.
 *
 * Because Storybook does not wire TanStack Query, this story is a visual
 * reference only; use the test suite for behavioural coverage.
 */
export const WithError: Story = {};
