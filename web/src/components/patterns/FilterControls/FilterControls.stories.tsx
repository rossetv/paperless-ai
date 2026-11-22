import type { Meta, StoryObj } from '@storybook/react-vite';
import type { FilterRequest } from '../../../api/types';
import { FilterControls } from './FilterControls';

// Stories that use useFacets rely on the QueryClient provider in .storybook/preview.tsx.

const emptyFilters: FilterRequest = { tag_ids: [] };

const meta = {
  title: 'Patterns/FilterControls',
  component: FilterControls,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof FilterControls>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    filters: emptyFilters,
    onFiltersChange: (f) => console.log('filters changed:', f),
  },
};

export const WithActiveFilters: Story = {
  args: {
    filters: {
      correspondent_id: 1,
      document_type_id: 10,
      tag_ids: [100],
    },
    onFiltersChange: (f) => console.log('filters changed:', f),
  },
};

export const CollapsedOnMobile: Story = {
  args: {
    filters: emptyFilters,
    defaultExpanded: false,
    onFiltersChange: (f) => console.log('filters changed:', f),
  },
};
