import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { DocumentScreen } from '../features/document/DocumentScreen/DocumentScreen';
import { DocumentErrorScreen } from '../features/document/DocumentErrorScreen/DocumentErrorScreen';
import { FullPageLoading } from '../components/layout/FullPageLoading/FullPageLoading';
import { useDocument, useMe } from '../api/hooks';
import { ApiError } from '../api/client';

/**
 * The `/library/document/:id` route — the full-page document view opened
 * from the library list, but addressable as a shareable URL.
 *
 * Resolves the document by id via `useDocument`. Navigation back to the
 * library is handled by the breadcrumb inside `DocumentScreen`; parent
 * filter / sort / page state is preserved via `parentSearch`.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */
export function LibraryDocumentPage(): React.ReactElement {
  const { id } = useParams<{ id: string }>();
  const parsed = id !== undefined ? Number.parseInt(id, 10) : NaN;
  const documentId = Number.isFinite(parsed) ? parsed : null;
  const [searchParams] = useSearchParams();

  const docQuery = useDocument(documentId);
  const me = useMe();
  // Derive the role for ActionsCard / DocumentScreen. Treat an unresolved me
  // query (still loading) as 'readonly' so the screen renders immediately
  // without waiting — editing affordances appear once me resolves.
  const meRole = me.data?.user?.role;
  const role = meRole === 'admin' ? 'admin' : meRole === 'member' ? 'member' : 'readonly';

  if (docQuery.isLoading) return <FullPageLoading />;

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

  const parentSearchString = searchParams.toString();
  return (
    <Page>
      <AppNavBar />
      <DocumentScreen
        document={docQuery.data}
        parent="library"
        parentSearch={parentSearchString === '' ? '' : `?${parentSearchString}`}
        role={role}
      />
    </Page>
  );
}
