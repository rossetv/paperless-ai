import React from 'react';
import type { Meta, StoryObj } from '@storybook/react';
import { Button } from '../../primitives/Button/Button';
import { EmptyState } from './EmptyState';

const meta = {
  title: 'Patterns/EmptyState',
  component: EmptyState,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    message: { control: 'text' },
    description: { control: 'text' },
  },
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NoResults: Story = {
  args: {
    icon: 'search',
    message: 'No results found',
    description: 'Try adjusting your search query or removing some filters.',
  },
};

export const EmptyDocuments: Story = {
  args: {
    icon: 'document',
    message: 'No documents yet',
    description: 'Documents will appear here once they have been indexed.',
  },
};

export const WithAction: Story = {
  args: {
    icon: 'search',
    message: 'Nothing to see here',
    description: 'Start by running a search to find relevant documents.',
    action: (
      <Button onClick={() => { /* story noop */ }}>Search documents</Button>
    ),
  },
};

export const Minimal: Story = {
  args: {
    icon: 'info',
    message: 'No items available',
  },
};
