import React from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { DocumentPreviewScreen } from '../features/search/DocumentPreviewScreen/DocumentPreviewScreen';
import { DocumentErrorScreen } from '../features/document/DocumentErrorScreen/DocumentErrorScreen';
import { FullPageLoading } from '../components/layout/FullPageLoading/FullPageLoading';
import { useDocument } from '../api/hooks';
import { ApiError } from '../api/client';

/**
 * The `/library/document/:id` route — the document-preview overlay opened
 * from the library list, but addressable as a shareable URL.
 *
 * Resolves the document by id via `useDocument` (the library list cache is
 * read-through, so navigating from the list is instant). On close, navigates
 * to `/library?<parent params>` so the parent's filter / sort / page state
 * is restored — including the cold-start case where the recipient has no
 * library list in memory.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */
export function LibraryDocumentPage(): React.ReactElement {
  const { id } = useParams<{ id: string }>();
  const parsed = id !== undefined ? Number.parseInt(id, 10) : NaN;
  const documentId = Number.isFinite(parsed) ? parsed : null;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const docQuery = useDocument(documentId);

  function close(): void {
    const search = searchParams.toString();
    navigate(`/library${search === '' ? '' : `?${search}`}`);
  }

  if (docQuery.isLoading) {
    return <FullPageLoading />;
  }

  if (docQuery.isError || docQuery.data === undefined) {
    const notFound =
      docQuery.error instanceof ApiError && docQuery.error.status === 404;
    return (
      <Page>
        <AppNavBar />
        <DocumentErrorScreen notFound={notFound} />
      </Page>
    );
  }

  const doc = docQuery.data;
  const source = {
    document_id: doc.id,
    title: doc.title,
    correspondent: doc.correspondent,
    document_type: doc.document_type,
    created: doc.created,
    snippet: '',
    score: 0,
    paperless_url: null,
    tags: doc.tags,
  };

  return (
    <DocumentPreviewScreen
      source={source}
      onClose={close}
      sourceIndex={1}
      sourceCount={1}
    />
  );
}
