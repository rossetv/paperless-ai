import type { Meta, StoryObj } from '@storybook/react';
import { DaemonCard } from './DaemonCard';

const meta = {
  title: 'Features/Index/DaemonCard',
  component: DaemonCard,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof DaemonCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Running: Story = {
  args: {
    daemon: {
      name: 'ocr',
      state: 'running',
      detail: '3 documents in flight',
      processed_count: 412,
      last_heartbeat: '2026-05-22T08:59:50Z',
    },
  },
};

export const Idle: Story = {
  args: {
    daemon: {
      name: 'indexer',
      state: 'idle',
      detail: 'idle',
      processed_count: 14238,
      last_heartbeat: '2026-05-22T08:58:00Z',
    },
  },
};

export const Stopped: Story = {
  args: {
    daemon: {
      name: 'classifier',
      state: 'stopped',
      detail: 'idle',
      processed_count: 0,
      last_heartbeat: '2026-05-21T22:00:00Z',
    },
  },
};

/** The four-card daemon row from the Index dashboard. */
export const Row: StoryObj = {
  render: () => (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 'var(--spacing-10)',
      }}
    >
      <DaemonCard daemon={Running.args!.daemon} />
      <DaemonCard
        daemon={{
          name: 'classifier',
          state: 'running',
          detail: '1 document in flight',
          processed_count: 62,
          last_heartbeat: '2026-05-22T08:59:48Z',
        }}
      />
      <DaemonCard daemon={Idle.args!.daemon} />
      <DaemonCard
        daemon={{
          name: 'search',
          state: 'running',
          detail: 'serving',
          processed_count: 0,
          last_heartbeat: '2026-05-22T08:59:55Z',
        }}
      />
    </div>
  ),
};
