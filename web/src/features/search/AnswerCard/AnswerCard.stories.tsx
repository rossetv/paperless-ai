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
  },
  {
    document_id: 2,
    title: 'Installation Invoice',
    correspondent: 'Smith Plumbing Ltd',
    document_type: 'Invoice',
    created: '2021-03-16',
    snippet: 'Labour and parts for boiler installation, total £1,240.',
    paperless_url: 'https://paperless.example.com/documents/2/',
    score: 0.88,
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
      'Your boiler was installed in March 2021 [1] by Smith Plumbing Ltd, who charged £1,240 for the work [2].',
    sources,
    onCitationActivate: (index) => console.log('Citation activated:', index),
  },
};

export const NoCitations: Story = {
  args: {
    answer: 'No documents were found matching your query.',
    sources: [],
  },
};

export const LongAnswer: Story = {
  args: {
    answer:
      'The boiler warranty [1] is valid for five years from the installation date. The installer [2] is responsible for registering the warranty within 30 days. Failure to register may void the extended warranty period. Please contact the manufacturer [1] directly for claims.',
    sources,
  },
};
