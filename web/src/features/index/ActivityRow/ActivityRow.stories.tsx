import type { Meta, StoryObj } from '@storybook/react';
import { ActivityRow } from './ActivityRow';

const meta = {
  title: 'Features/Index/ActivityRow',
  component: ActivityRow,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof ActivityRow>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Complete: Story = {
  args: {
    entry: {
      id: 'r1',
      status: 'ok',
      label: 'Reconcile cycle complete',
      detail: '+12 new · 3 updated · 0 deleted · 312 chunks embedded · 1.8s',
      at: '2026-05-22T08:56:00Z',
    },
  },
};

export const NextCycle: Story = {
  args: {
    entry: {
      id: 'next',
      status: 'idle',
      label: 'Next cycle in 4m 21s',
      detail: 'Polling Paperless for changes…',
      at: null,
    },
  },
};

/** A short reconcile-activity list. */
export const List: StoryObj = {
  render: () => {
    const entries = [
      { id: 'next', status: 'idle' as const, label: 'Next cycle in 4m 21s', detail: 'Polling Paperless for changes…', at: null },
      { id: 'r1', status: 'ok' as const, label: 'Reconcile cycle complete', detail: '+12 new · 3 updated · 312 chunks embedded · 1.8s', at: '2026-05-22T08:56:00Z' },
      { id: 'r2', status: 'warn' as const, label: 'Deletion sweep complete', detail: '−2 stale rows pruned · 4 orphaned chunks removed · 12.3s', at: '2026-05-22T08:00:00Z' },
      { id: 'r3', status: 'error' as const, label: 'Reconcile cycle failed', detail: 'Paperless API returned 502 — retried next cycle', at: '2026-05-22T06:00:00Z' },
    ];
    return (
      <div>
        {entries.map((e, i) => (
          <ActivityRow key={e.id} entry={e} last={i === entries.length - 1} />
        ))}
      </div>
    );
  },
};
