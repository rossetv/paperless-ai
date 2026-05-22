import type { Meta, StoryObj } from '@storybook/react';
import { NoResultsScreen } from './NoResultsScreen';

/**
 * NoResultsScreen embeds `FilterControls`, which drives `useFacets`.
 * Storybook does not wire TanStack Query, so this is a structural reference.
 */
const meta = {
  title: 'Features/Search/NoResultsScreen',
  component: NoResultsScreen,
  parameters: { layout: 'fullscreen' },
  args: {
    query: 'payslip from 2019 with a bonus over £4000',
    filters: {
      tag_ids: [],
      correspondent_id: null,
      document_type_id: null,
      date_from: null,
      date_to: null,
    },
    onFiltersChange: () => {},
    onClearFilters: () => globalThis.console.log('clear filters'),
    onSearchWithoutFilters: () => globalThis.console.log('search no filters'),
  },
} satisfies Meta<typeof NoResultsScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
