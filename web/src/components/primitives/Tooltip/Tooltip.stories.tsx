import type { Meta, StoryObj } from '@storybook/react';
import { Tooltip } from './Tooltip';
import { Button } from '../Button/Button';
import { Icon } from '../Icon/Icon';

const meta = {
  title: 'Primitives/Tooltip',
  component: Tooltip,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    content: { control: 'text' },
  },
} satisfies Meta<typeof Tooltip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OnButton: Story = {
  args: {
    content: 'Opens document in Paperless',
    children: <Button>View document</Button>,
  },
};

export const OnIconButton: StoryObj = {
  args: {
    content: 'Search documents',
    children: (
      <button
        type="button"
        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 'var(--spacing-6)' }}
      >
        <Icon name="search" size="medium" />
      </button>
    ),
  },
};

export const LongContent: Story = {
  args: {
    content: 'Relevance score based on semantic similarity to your query',
    children: <Button variant="secondary">Score</Button>,
  },
};

export const MultipleTooltips: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: '1rem' }}>
      <Tooltip content="Add filter">
        <Button>Filter</Button>
      </Tooltip>
      <Tooltip content="Open in Paperless-ngx">
        <Button variant="secondary">Open</Button>
      </Tooltip>
      <Tooltip content="Copy document ID">
        <Button variant="secondary">Copy</Button>
      </Tooltip>
    </div>
  ),
};
