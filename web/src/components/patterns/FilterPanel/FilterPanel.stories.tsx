import type { Meta, StoryObj } from '@storybook/react';
import { Chip } from '../../primitives/Chip/Chip';
import { Stack } from '../../layout/Stack/Stack';
import { FilterPanel } from './FilterPanel';

const meta = {
  title: 'Patterns/FilterPanel',
  component: FilterPanel,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
  argTypes: {
    defaultExpanded: { control: 'boolean' },
    title: { control: 'text' },
  },
} satisfies Meta<typeof FilterPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ExpandedByDefault: Story = {
  args: {
    title: 'Date range',
    children: (
      <Stack direction="vertical" gap={3}>
        <label>
          From
          <input type="date" />
        </label>
        <label>
          To
          <input type="date" />
        </label>
      </Stack>
    ),
  },
};

export const CollapsedByDefault: Story = {
  args: {
    title: 'Document type',
    defaultExpanded: false,
    children: <p>Document type options would appear here.</p>,
  },
};

export const WithRichContent: Story = {
  args: {
    title: 'Tags',
    // Real Chip primitives — the story exercises the pattern with genuine
    // library components rather than ad-hoc styled tag spans.
    children: (
      <Stack direction="horizontal" gap={3} wrap>
        {['Invoice', 'Receipt', 'Contract', 'Letter', 'Statement'].map((tag) => (
          <Chip key={tag}>{tag}</Chip>
        ))}
      </Stack>
    ),
  },
};

export const Stacked: StoryObj = {
  render: () => (
    <Stack direction="vertical" gap={3}>
      <FilterPanel title="Date range">
        <p>Date filter controls</p>
      </FilterPanel>
      <FilterPanel title="Document type" defaultExpanded={false}>
        <p>Type filter controls</p>
      </FilterPanel>
      <FilterPanel title="Tags">
        <p>Tag filter controls</p>
      </FilterPanel>
    </Stack>
  ),
};
