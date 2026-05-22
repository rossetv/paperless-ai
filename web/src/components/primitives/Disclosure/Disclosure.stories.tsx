import type { Meta, StoryObj } from '@storybook/react';
import { Disclosure } from './Disclosure';

const meta = {
  title: 'Primitives/Disclosure',
  component: Disclosure,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof Disclosure>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Collapsed: Story = {
  args: {
    summary: <span>How this answer was built</span>,
    children: <p>Three semantic queries, five keyword terms.</p>,
  },
};

export const Open: Story = {
  args: {
    summary: <span>How this answer was built</span>,
    defaultOpen: true,
    children: <p>Three semantic queries, five keyword terms.</p>,
  },
};
