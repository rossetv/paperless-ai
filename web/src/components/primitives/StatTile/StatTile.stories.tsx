import type { Meta, StoryObj } from '@storybook/react';
import { StatTile } from './StatTile';

const meta = {
  title: 'Primitives/StatTile',
  component: StatTile,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof StatTile>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { value: '187,612', label: 'Semantic chunks', sub: '2,000 chars · 256 overlap' },
};

export const Accent: Story = {
  args: {
    value: '14,238',
    label: 'Documents indexed',
    sub: '+12 in the last cycle',
    accent: true,
  },
};

export const WithoutSubLine: Story = {
  args: { value: '842 MB', label: 'Index size on disk' },
};

/** The four-tile row from the Index dashboard. */
export const Row: StoryObj = {
  render: () => (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 'var(--spacing-10)',
      }}
    >
      <StatTile value="14,238" label="Documents indexed" sub="+12 in the last cycle" accent />
      <StatTile value="187,612" label="Semantic chunks" sub="2,000 chars · 256 overlap" />
      <StatTile value="text-embedding-3-small" label="Embedding model" sub="1,536 dimensions" />
      <StatTile value="842 MB" label="Index size on disk" sub="/data/index.db" />
    </div>
  ),
};
