/**
 * DocumentScreen — full-page document composition (Wave C: actions wired up).
 *
 * Layout: centred container with breadcrumb, title row (DocumentTitle +
 * SaveStatusPill), submeta line, and a two-column grid (PDF viewer | sidebar).
 *
 * Sidebar: MetadataCard (correspondent, document type, document date) +
 * TagEditor card + ActionsCard (Re-classify, Re-transcribe; Delete for admin).
 *
 * The `role` prop replaces the previous `canEdit: boolean` — a single source of
 * truth from which canEdit is derived internally (`role !== 'readonly'`).
 *
 * Deferred from v1 (require extending the LibraryDocument wire shape):
 *   - Notes editing: `LibraryDocument.notes` is not yet returned by GET /api/documents.
 *   - Archive serial number editing: not in `LibraryDocument` either.
 * Both can be added in a follow-up task once the backend query is extended.
 */
import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { LibraryDocument } from '../../../api/types';
import {
  useUpdateDocument,
  useCorrespondents,
  useDocumentTypes,
  useTags,
  useCreateCorrespondent,
  useCreateDocumentType,
  useCreateTag,
  useReclassifyDocument,
  useRetranscribeDocument,
  useDeleteDocument,
} from '../../../api/hooks';
import { Card } from '../../../components/primitives/Card/Card';
import { DocumentTitle } from '../DocumentTitle/DocumentTitle';
import { PdfViewerCard } from '../PdfViewerCard/PdfViewerCard';
import { MetadataCard } from '../MetadataCard/MetadataCard';
import { TagEditor } from '../TagEditor/TagEditor';
import { SaveStatusPill, type SaveStatus } from '../SaveStatusPill/SaveStatusPill';
import { ActionsCard, type Role } from '../ActionsCard/ActionsCard';
import { MatchCard } from '../MatchCard/MatchCard';
import { parseSearchParams } from '../../search/parseSearchParams';
import styles from './DocumentScreen.module.css';

export type { Role };

export interface DocumentScreenProps {
  /** The document to display. */
  document: LibraryDocument;
  /** Which parent screen opened this document. */
  parent: 'library' | 'search';
  /**
   * Parent URL search-string (e.g. "?tag=12" or "?q=invoice") — included
   * verbatim on the breadcrumb link so the parent's state is restorable.
   */
  parentSearch: string;
  /**
   * Access role of the signed-in user.
   *
   * - 'admin': full edit + delete access.
   * - 'member': edit access, no delete.
   * - 'readonly': view only, no editing or actions.
   *
   * `canEdit` is derived internally from this: `role !== 'readonly'`.
   */
  role: Role;
}

/**
 * Full-page composition for a single document.
 *
 * `DocumentScreen` owns one `useUpdateDocument` mutation. The `saveStatus`
 * derived from the mutation lifecycle drives the `SaveStatusPill`. All editing
 * callbacks delegate to `update.mutate`, which writes to the
 * `['document', id]` cache and invalidates the library + search queries on
 * success.
 *
 * The `ActionsCard` fires reclassify / retranscribe / delete mutations; on
 * successful delete the component navigates to the breadcrumb href.
 */
export function DocumentScreen({
  document,
  parent,
  parentSearch,
  role,
}: DocumentScreenProps): React.ReactElement {
  const navigate = useNavigate();
  const update = useUpdateDocument();
  const correspondents = useCorrespondents();
  const documentTypes = useDocumentTypes();
  const tags = useTags();
  const createCorrespondent = useCreateCorrespondent();
  const createDocumentType = useCreateDocumentType();
  const createTag = useCreateTag();
  const reclassify = useReclassifyDocument();
  const retranscribe = useRetranscribeDocument();
  const deleteDoc = useDeleteDocument();

  const canEdit = role !== 'readonly';

  // Reset the mutation success state after 2 s so the pill cycles back to idle.
  React.useEffect(() => {
    if (!update.isSuccess) return;
    const id = window.setTimeout(() => update.reset(), 2_000);
    return () => window.clearTimeout(id);
  }, [update.isSuccess, update]);

  const saveStatus: SaveStatus = !canEdit
    ? 'readonly'
    : update.isPending ? 'saving'
    : update.isError   ? 'error'
    : update.isSuccess ? 'saved'
    : 'idle';

  const breadcrumbHref =
    parent === 'library' ? `/library${parentSearch}` : `/${parentSearch}`;
  const breadcrumbLabel = parent === 'library' ? 'Library' : 'Search results';

  // Parse the parent search string into query + filters so MatchCard can look
  // up this document's position in the search results that led here.
  const { query: parentQuery, filters: parentFilters } = React.useMemo(
    () => parseSearchParams(parentSearch),
    [parentSearch],
  );

  // ── Tag id resolution ────────────────────────────────────────────────────
  // `document.tags` carries name strings. We resolve ids by name from the tag
  // list so the TagEditor (which operates on ids) can work correctly.
  const tagsByName = React.useMemo(
    () => new Map((tags.data ?? []).map((t) => [t.name, t])),
    [tags.data],
  );

  const currentTagIds = React.useMemo(
    () =>
      document.tags
        .map((name) => tagsByName.get(name)?.id)
        .filter((id): id is number => id !== undefined),
    [document.tags, tagsByName],
  );

  // ── Mutation helpers ──────────────────────────────────────────────────────

  function commitTitle(next: string): void {
    update.mutate({ id: document.id, patch: { title: next === '' ? null : next } });
  }

  function addTag(id: number): void {
    update.mutate({ id: document.id, patch: { tags: [...currentTagIds, id] } });
  }

  function removeTag(id: number): void {
    update.mutate({ id: document.id, patch: { tags: currentTagIds.filter((t) => t !== id) } });
  }

  function createTagThenAdd(name: string): void {
    createTag.mutate(name, {
      onSuccess: (created) => {
        update.mutate({ id: document.id, patch: { tags: [...currentTagIds, created.id] } });
      },
    });
  }

  return (
    <main className={styles['page']}>
      <Link to={breadcrumbHref} className={styles['crumb']}>
        ← {breadcrumbLabel}
      </Link>

      <div className={styles['title-row']}>
        <DocumentTitle title={document.title} canEdit={canEdit} onChange={commitTitle} />
        {saveStatus === 'error' ? (
          <SaveStatusPill status={saveStatus} onRetry={() => update.reset()} />
        ) : (
          <SaveStatusPill status={saveStatus} />
        )}
      </div>

      <div className={styles['submeta']}>
        <span>
          Document <strong>#{document.id}</strong>
        </span>
        {document.page_count !== null && (
          <>
            <span className={styles['sep']}>·</span>
            <span>
              {document.page_count} {document.page_count === 1 ? 'page' : 'pages'}
            </span>
          </>
        )}
      </div>

      <div className={styles['grid']}>
        <PdfViewerCard
          documentId={document.id}
          title={document.title ?? `Document ${document.id}`}
          paperlessUrl={document.paperless_url}
        />

        <aside className={styles['side']}>
          {parent === 'search' && (
            <MatchCard
              documentId={document.id}
              query={parentQuery}
              filters={parentFilters}
            />
          )}

          <MetadataCard
            document={document}
            correspondents={correspondents.data ?? []}
            documentTypes={documentTypes.data ?? []}
            canEdit={canEdit}
            onPatch={(patch) => update.mutate({ id: document.id, patch })}
            onCreateCorrespondent={(name) => createCorrespondent.mutate(name)}
            onCreateDocumentType={(name) => createDocumentType.mutate(name)}
          />

          <Card>
            <h3 className={styles['card-h']}>Tags</h3>
            <TagEditor
              selectedIds={currentTagIds}
              availableTags={tags.data ?? []}
              canEdit={canEdit}
              onAdd={addTag}
              onRemove={removeTag}
              onCreate={createTagThenAdd}
            />
          </Card>

          <ActionsCard
            documentId={document.id}
            title={document.title ?? `Document ${document.id}`}
            role={role}
            onReclassify={(id) =>
              reclassify.mutate(id, {
                onSuccess: () => {
                  /* TODO: toast — add in a follow-up task */
                },
              })
            }
            onRetranscribe={(id) => retranscribe.mutate(id)}
            onDelete={(id) =>
              deleteDoc.mutate(id, {
                onSuccess: () => navigate(breadcrumbHref),
              })
            }
          />
        </aside>
      </div>
    </main>
  );
}
