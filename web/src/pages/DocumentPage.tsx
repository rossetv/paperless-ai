import React from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { DocumentScreen } from '../features/document/DocumentScreen/DocumentScreen';
import { DocumentErrorScreen } from '../features/document/DocumentErrorScreen/DocumentErrorScreen';
import { IndexNotReadyScreen } from '../features/search/IndexNotReadyScreen/IndexNotReadyScreen';
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
 */
export function DocumentPage(): React.ReactElement {
  const { id } = useParams<{ id: string }>();
  const parsed = id !== undefined ? Number.parseInt(id, 10) : NaN;
  const documentId = Number.isFinite(parsed) ? parsed : null;
  const [searchParams] = useSearchParams();

  const docQuery = useDocument(documentId);
  const me = useMe();
  // Treat an unresolved `me` as 'readonly' so the screen renders immediately;
  // editing affordances appear once it resolves.
  const meRole = me.data?.user?.role;
  const role = meRole === 'admin' ? 'admin' : meRole === 'member' ? 'member' : 'readonly';

  if (docQuery.isLoading) return <FullPageLoading />;

  // A cached copy survives a failed refetch, but not a 404: the document is gone.
  const notFound = docQuery.error instanceof ApiError && docQuery.error.status === 404;

  if (docQuery.data === undefined || notFound) {
    if (docQuery.error instanceof ApiError && docQuery.error.status === 503) {
      return (
        <Page nav={<AppNavBar />}>
          <IndexNotReadyScreen messageAs="h1" onRetry={() => void docQuery.refetch()} />
        </Page>
      );
    }
    return (
      <Page nav={<AppNavBar />}>
        <DocumentErrorScreen notFound={notFound} />
      </Page>
    );
  }

  const parent: 'library' | 'search' = searchParams.has('q') ? 'search' : 'library';
  const parentSearchString = parent === 'search' ? searchParams.toString() : '';
  return (
    <Page nav={<AppNavBar />}>
      <DocumentScreen
        key={docQuery.data.id}
        document={docQuery.data}
        parent={parent}
        parentSearch={parentSearchString === '' ? '' : `?${parentSearchString}`}
        role={role}
      />
    </Page>
  );
}
