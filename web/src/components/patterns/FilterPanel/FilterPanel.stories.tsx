import type { Meta, StoryObj } from '@storybook/react';
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
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <label>
          From
          <input type="date" />
        </label>
        <label>
          To
          <input type="date" />
        </label>
      </div>
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
    children: (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
        {['Invoice', 'Receipt', 'Contract', 'Letter', 'Statement'].map((tag) => (
          <span
            key={tag}
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              background: '#f5f5f7',
              fontSize: '14px',
            }}
          >
            {tag}
          </span>
        ))}
      </div>
    ),
  },
};

export const Stacked: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', width: '300px' }}>
      <FilterPanel title="Date range">
        <p>Date filter controls</p>
      </FilterPanel>
      <FilterPanel title="Document type" defaultExpanded={false}>
        <p>Type filter controls</p>
      </FilterPanel>
      <FilterPanel title="Tags">
        <p>Tag filter controls</p>
      </FilterPanel>
    </div>
  ),
};
