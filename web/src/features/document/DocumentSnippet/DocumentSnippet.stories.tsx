import type { Meta, StoryObj } from '@storybook/react';
import { DocumentSnippet } from './DocumentSnippet';

const meta = {
  title: 'Features/Document/DocumentSnippet',
  component: DocumentSnippet,
  parameters: {
    layout: 'padded',
  },
} satisfies Meta<typeof DocumentSnippet>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Snippet with OCR-extracted text. */
export const WithSnippet: Story = {
  args: {
    snippet: 'The boiler model EcoTec Plus 838 was installed on 15 March 2021 at 12 Oak Street. The warranty covers parts and labour for five years from the date of installation.',
  },
};

/** Empty snippet — shown when the server had no excerpt for the document. */
export const EmptySnippet: Story = {
  args: {
    snippet: '',
  },
};
