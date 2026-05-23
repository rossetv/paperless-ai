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
      key: 'ocr',
      name: 'OCR',
      role: 'Vision-model transcription of scanned pages',
      state: 'running',
      detail: '3 documents in flight',
      throughput: '412 pages / hr',
    },
  },
};

export const Idle: Story = {
  args: {
    daemon: {
      key: 'indexer',
      name: 'Indexer',
      role: 'Reconciles Paperless into the SQLite index',
      state: 'idle',
      detail: 'Next cycle in 4m 21s',
      throughput: 'incremental',
    },
  },
};

export const Stopped: Story = {
  args: {
    daemon: {
      key: 'classifier',
      name: 'Classifier',
      role: 'Title, correspondent, type, tags',
      state: 'stopped',
      detail: 'Process not running',
      throughput: '—',
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
          key: 'classifier',
          name: 'Classifier',
          role: 'Title, correspondent, type, tags',
          state: 'running',
          detail: '1 document in flight',
          throughput: '62 docs / hr',
        }}
      />
      <DaemonCard daemon={Idle.args!.daemon} />
      <DaemonCard
        daemon={{
          key: 'search',
          name: 'Search',
          role: 'HTTP + MCP server',
          state: 'running',
          detail: '0 in-flight / 4 concurrent cap',
          throughput: '0 RPS',
        }}
      />
    </div>
  ),
};
