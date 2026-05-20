import { render, screen } from '@testing-library/react';
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

describe('DocumentMeta', () => {
  it('renders the correspondent when present', () => {
    render(<DocumentMeta source={fullDocument} />);
    expect(screen.getByText('British Gas')).toBeInTheDocument();
  });

  it('renders the document type when present', () => {
    render(<DocumentMeta source={fullDocument} />);
    expect(screen.getByText('Invoice')).toBeInTheDocument();
  });

  it('renders the created date when present', () => {
    render(<DocumentMeta source={fullDocument} />);
    expect(screen.getByText('2023-04-12')).toBeInTheDocument();
  });

  it('does not render a correspondent badge when correspondent is null', () => {
    render(<DocumentMeta source={minimalDocument} />);
    // When all optional fields are null, nothing from the full set should appear
    expect(screen.queryByText('British Gas')).not.toBeInTheDocument();
  });

  it('does not render a document type badge when document_type is null', () => {
    render(<DocumentMeta source={minimalDocument} />);
    expect(screen.queryByText('Invoice')).not.toBeInTheDocument();
  });

  it('does not render a date when created is null', () => {
    render(<DocumentMeta source={minimalDocument} />);
    expect(screen.queryByText('2023-04-12')).not.toBeInTheDocument();
  });

  it('renders without crashing when all optional fields are null', () => {
    // Should not throw; just render an empty (but valid) component
    expect(() => render(<DocumentMeta source={minimalDocument} />)).not.toThrow();
  });

  it('uses a <time> element with dateTime attribute for the created date', () => {
    render(<DocumentMeta source={fullDocument} />);
    const timeEl = document.querySelector('time');
    expect(timeEl).toBeInTheDocument();
    expect(timeEl).toHaveAttribute('dateTime', '2023-04-12');
  });
});
