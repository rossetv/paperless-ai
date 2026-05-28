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
 * The `/document/:id` route — the full-page document view addressable
 * standalone (no library/search parent context) or from a search-result link.
 *
 * Parent context: if the URL carries a search query (`?q=…`) the breadcrumb
 * in `DocumentScreen` links back to `/?<params>` so the user returns to the
 * same result list; otherwise it links to `/library` as the default.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */
export function DocumentPage(): React.ReactElement {
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

  const parent: 'library' | 'search' = searchParams.has('q') ? 'search' : 'library';
  const parentSearchString = parent === 'search' ? searchParams.toString() : '';
  return (
    <Page>
      <AppNavBar />
      <DocumentScreen
        document={docQuery.data}
        parent={parent}
        parentSearch={parentSearchString === '' ? '' : `?${parentSearchString}`}
        role={role}
      />
    </Page>
  );
}
