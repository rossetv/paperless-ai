import type { Meta, StoryObj } from '@storybook/react';
import { SnippetText } from './SnippetText';

const meta = {
  title: 'Primitives/SnippetText',
  component: SnippetText,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
} satisfies Meta<typeof SnippetText>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithHighlight: Story = {
  args: {
    text: 'Twelve equal monthly direct debits of **£153.94** were collected, with a **£0.00** closing balance.',
  },
};

export const Plain: Story = {
  args: { text: 'No emphasised phrases in this excerpt.' },
};

export const Empty: Story = { args: { text: '' } };
