import type { Meta, StoryObj } from '@storybook/react';
import { ViewerSplit } from './ViewerSplit';

const meta = {
  title: 'Layout/ViewerSplit',
  component: ViewerSplit,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
} satisfies Meta<typeof ViewerSplit>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    sidebar: <div style={{ padding: 'var(--spacing-14)' }}>Sidebar</div>,
    children: (
      <div style={{ height: '480px', background: 'var(--colour-overlay)' }} />
    ),
  },
};
