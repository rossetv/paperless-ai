import type { Meta, StoryObj } from '@storybook/react';
import { Tabs } from './Tabs';

const meta = {
  title: 'Patterns/Tabs',
  component: Tabs,
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof Tabs>;

export default meta;
type Story = StoryObj<typeof meta>;

const DEMO_TABS = [
  {
    id: 'results',
    label: 'Results',
    content: (
      <div>
        <p>Search results will appear here.</p>
      </div>
    ),
  },
  {
    id: 'sources',
    label: 'Sources',
    content: (
      <div>
        <p>Source documents will be listed here.</p>
      </div>
    ),
  },
  {
    id: 'plan',
    label: 'Query plan',
    content: (
      <div>
        <p>The query plan and debug information will appear here.</p>
      </div>
    ),
  },
];

export const Default: Story = {
  args: {
    tabs: DEMO_TABS,
  },
};

export const DefaultToSecondTab: Story = {
  args: {
    tabs: DEMO_TABS,
    defaultActiveId: 'sources',
  },
};

export const TwoTabs: Story = {
  args: {
    tabs: [
      {
        id: 'answer',
        label: 'Answer',
        content: <p>The synthesised answer goes here.</p>,
      },
      {
        id: 'raw',
        label: 'Raw sources',
        content: <p>Unfiltered source documents go here.</p>,
      },
    ],
  },
};
