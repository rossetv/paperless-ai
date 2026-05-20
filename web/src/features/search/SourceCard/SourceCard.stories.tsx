import type { Meta, StoryObj } from '@storybook/react';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from './SourceCard';

const fullSource: SourceDocument = {
  document_id: 42,
  title: 'Boiler Warranty Certificate',
  correspondent: 'Vaillant',
  document_type: 'Certificate',
  created: '2021-03-15',
  snippet: 'The boiler model EcoTec Plus 838 was installed on 15 March 2021 at 12 Oak Street. The warranty covers parts and labour for five years.',
  paperless_url: 'https://paperless.example.com/documents/42/',
  score: 0.95,
};

const minimalSource: SourceDocument = {
  document_id: 1,
  title: null,
  correspondent: null,
  document_type: null,
  created: null,
  snippet: 'Only a text snippet is available for this document.',
  paperless_url: 'https://paperless.example.com/documents/1/',
  score: 0.5,
};

const meta = {
  title: 'Features/Search/SourceCard',
  component: SourceCard,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof SourceCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Full: Story = {
  args: {
    source: fullSource,
    index: 1,
  },
};

export const Highlighted: Story = {
  args: {
    source: fullSource,
    index: 1,
    highlighted: true,
  },
};

export const Minimal: Story = {
  args: {
    source: minimalSource,
    index: 2,
  },
};
