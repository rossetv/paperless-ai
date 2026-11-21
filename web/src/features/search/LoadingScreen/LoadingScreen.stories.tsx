import type { Meta, StoryObj } from '@storybook/react';
import { LoadingScreen } from './LoadingScreen';

/**
 * `FilterControls` needs TanStack Query, which Storybook does not wire, so this
 * is a structural reference only; behaviour is covered by the tests.
 */
const meta = {
  title: 'Features/Search/LoadingScreen',
  component: LoadingScreen,
  parameters: { layout: 'fullscreen' },
  args: {
    query: 'How much did I pay Npower across 2024?',
    filters: {
      tag_ids: [],
      correspondent_id: null,
      document_type_id: null,
      date_from: null,
      date_to: null,
    },
    onFiltersChange: () => {},
    // A representative mid-stream snapshot: planning and retrieval done, the
    // judge currently running.
    phaseRecords: [
      {
        phase: 'plan',
        label: 'Planning the query',
        detail: {
          rewritten_query: 'Total Npower energy payments in 2024',
          skipped_trivial: false,
        },
        tokens: { prompt: 1180, completion: 64, reasoning: 0, total: 1244 },
        cost: { usd: 0.004, local: false },
        ms: 410,
      },
      {
        phase: 'retrieve',
        label: 'Retrieving documents',
        detail: { chunk_count: 18, doc_count: 6, broadened: false },
        tokens: null,
        cost: null,
        ms: 120,
      },
    ],
    activePhase: 'judge',
  },
} satisfies Meta<typeof LoadingScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
