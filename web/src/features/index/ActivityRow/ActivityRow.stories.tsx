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
    cycle: {
      id: 1,
      kind: 'sync',
      started_at: '2026-05-22T08:56:00Z',
      finished_at: '2026-05-22T08:56:02Z',
      ok: true,
      summary: { indexed: 12, updated: 3, skipped: 0 },
      detail: 'incremental sync complete',
    },
  },
};

export const Failed: Story = {
  args: {
    cycle: {
      id: 2,
      kind: 'sync',
      started_at: '2026-05-22T06:00:00Z',
      finished_at: '2026-05-22T06:00:01Z',
      ok: false,
      summary: {},
      detail: 'Paperless API returned 502 — retried next cycle',
    },
  },
};

/** A short reconcile-activity list. */
export const List: StoryObj = {
  render: () => {
    const cycles = [
      {
        id: 3,
        kind: 'sync',
        started_at: '2026-05-22T08:56:00Z',
        finished_at: '2026-05-22T08:56:02Z',
        ok: true,
        summary: { indexed: 12, updated: 3 },
        detail: 'incremental sync complete',
      },
      {
        id: 2,
        kind: 'sweep',
        started_at: '2026-05-22T08:00:00Z',
        finished_at: '2026-05-22T08:00:12Z',
        ok: true,
        summary: { pruned: 2 },
        detail: 'deletion sweep complete',
      },
      {
        id: 1,
        kind: 'sync',
        started_at: '2026-05-22T06:00:00Z',
        finished_at: '2026-05-22T06:00:01Z',
        ok: false,
        summary: {},
        detail: 'Paperless API returned 502',
      },
    ];
    return (
      <div>
        {cycles.map((c, i) => (
          <ActivityRow key={c.id} cycle={c} last={i === cycles.length - 1} />
        ))}
      </div>
    );
  },
};
