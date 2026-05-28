/**
 * DocumentScreen — full-page document composition (Wave B: editing wired up).
 *
 * Layout: centred container with breadcrumb, title row (DocumentTitle +
 * SaveStatusPill), submeta line, and a two-column grid (PDF viewer | sidebar).
 *
 * Sidebar: MetadataCard (correspondent, document type, document date) +
 * TagEditor card.
 *
 * Deferred from v1 (require extending the LibraryDocument wire shape):
 *   - Notes editing: `LibraryDocument.notes` is not yet returned by GET /api/documents.
 *   - Archive serial number editing: not in `LibraryDocument` either.
 * Both can be added in a follow-up task once the backend query is extended.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import type { LibraryDocument } from '../../../api/types';
import {
  useUpdateDocument,
  useCorrespondents,
  useDocumentTypes,
  useTags,
  useCreateCorrespondent,
  useCreateDocumentType,
  useCreateTag,
} from '../../../api/hooks';
import { Card } from '../../../components/primitives/Card/Card';
import { DocumentTitle } from '../DocumentTitle/DocumentTitle';
import { PdfViewerCard } from '../PdfViewerCard/PdfViewerCard';
import { MetadataCard } from '../MetadataCard/MetadataCard';
import { TagEditor } from '../TagEditor/TagEditor';
import { SaveStatusPill, type SaveStatus } from '../SaveStatusPill/SaveStatusPill';
import styles from './DocumentScreen.module.css';

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
  /** Whether the current user may edit the document. */
  canEdit: boolean;
}

/**
 * Full-page composition for a single document.
 *
 * `DocumentScreen` owns one `useUpdateDocument` mutation. The `saveStatus`
 * derived from the mutation lifecycle drives the `SaveStatusPill`. All editing
 * callbacks delegate to `update.mutate`, which writes to the
 * `['document', id]` cache and invalidates the library + search queries on
 * success.
 */
export function DocumentScreen({
  document,
  parent,
  parentSearch,
  canEdit,
}: DocumentScreenProps): React.ReactElement {
  const update = useUpdateDocument();
  const correspondents = useCorrespondents();
  const documentTypes = useDocumentTypes();
  const tags = useTags();
  const createCorrespondent = useCreateCorrespondent();
  const createDocumentType = useCreateDocumentType();
  const createTag = useCreateTag();

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
        </aside>
      </div>
    </main>
  );
}
