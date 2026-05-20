import type { Meta, StoryObj } from '@storybook/react';
import { Container } from './Container';

const meta = {
  title: 'Layout/Container',
  component: Container,
  parameters: {
    layout: 'fullscreen',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof Container>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: (
      <div style={{ background: 'var(--colour-bg)', padding: 'var(--spacing-14)' }}>
        Centred content at the max content width.
      </div>
    ),
  },
};

export const WithCustomClass: Story = {
  args: {
    className: 'my-container',
    children: (
      <div style={{ background: 'var(--colour-bg)', padding: 'var(--spacing-14)' }}>
        Container with a custom className.
      </div>
    ),
  },
};
