import type { Meta, StoryObj } from '@storybook/react';
import { LoadingScreen } from './LoadingScreen';

/**
 * LoadingScreen embeds `FilterControls`, which drives `useFacets`. Storybook
 * does not wire TanStack Query, so this is a structural reference; behavioural
 * coverage lives in the test suite.
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
  },
} satisfies Meta<typeof LoadingScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
