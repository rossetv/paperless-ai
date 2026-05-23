import type { Meta, StoryObj } from '@storybook/react';
import type { SourceDocument } from '../../../api/types';
import { AnswerCard } from './AnswerCard';

const sources: SourceDocument[] = [
  {
    document_id: 1,
    title: 'Boiler Warranty Certificate',
    correspondent: 'Vaillant',
    document_type: 'Certificate',
    created: '2021-03-15',
    snippet: 'The boiler model EcoTec Plus 838 was installed on 15 March 2021.',
    paperless_url: 'https://paperless.example.com/documents/1/',
    score: 0.95,
    tags: [],
  },
  {
    document_id: 2,
    title: 'Installation Invoice',
    correspondent: 'Smith Plumbing Ltd',
    document_type: 'Invoice',
    created: '2021-03-16',
    snippet: 'Labour and parts for boiler installation, total GBP 1,240.',
    paperless_url: 'https://paperless.example.com/documents/2/',
    score: 0.88,
    tags: [],
  },
];

const meta = {
  title: 'Features/Search/AnswerCard',
  component: AnswerCard,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof AnswerCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithCitations: Story = {
  args: {
    answer:
      'Your boiler was installed in March 2021 [1] by Smith Plumbing Ltd, who charged GBP 1,240 for the work [2].',
    sources,
    stats: { llm_calls: 3, latency_ms: 1842, refined: false },
    onCitationActivate: (index) => globalThis.console.log('Citation', index),
  },
};

export const Refined: Story = {
  args: {
    answer:
      'The warranty [1] runs five years from installation; the installer [2] registers it within 30 days.',
    sources,
    stats: { llm_calls: 3, latency_ms: 2400, refined: true },
  },
};
