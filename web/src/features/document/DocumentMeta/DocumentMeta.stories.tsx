import type { Meta, StoryObj } from '@storybook/react';
import type { SourceDocument } from '../../../api/types';
import { DocumentMeta } from './DocumentMeta';

const fullDocument: SourceDocument = {
  document_id: 7,
  title: 'Boiler Service Report',
  correspondent: 'British Gas',
  document_type: 'Invoice',
  created: '2023-04-12',
  snippet: 'Annual service completed.',
  paperless_url: 'https://paperless.example.com/documents/7/',
  score: 0.9,
};

const correspondentOnlyDocument: SourceDocument = {
  ...fullDocument,
  document_type: null,
  created: null,
};

const minimalDocument: SourceDocument = {
  document_id: 8,
  title: null,
  correspondent: null,
  document_type: null,
  created: null,
  snippet: '',
  paperless_url: 'https://paperless.example.com/documents/8/',
  score: 0.5,
};

const meta = {
  title: 'Features/Document/DocumentMeta',
  component: DocumentMeta,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof DocumentMeta>;

export default meta;
type Story = StoryObj<typeof meta>;

/** All metadata fields populated. */
export const AllFields: Story = {
  args: { source: fullDocument },
};

/** Only the correspondent is present — document type and date are omitted. */
export const CorrespondentOnly: Story = {
  args: { source: correspondentOnlyDocument },
};

/** No optional fields — renders gracefully as an empty row. */
export const NoFields: Story = {
  args: { source: minimalDocument },
};
