/**
 * Full-page document view: breadcrumb, editable title with save status, the
 * PDF viewer, and a sidebar of metadata, tags and actions.
 */
import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { LibraryDocument } from '../../../api/types';
import { useQueryClient } from '@tanstack/react-query';
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
import { documentPdfUrl } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { DocumentTitle } from '../DocumentTitle/DocumentTitle';
import { DocumentActions } from '../DocumentActions/DocumentActions';
import { PdfViewerCard } from '../PdfViewerCard/PdfViewerCard';
import { MetadataCard } from '../MetadataCard/MetadataCard';
import { TagEditor } from '../TagEditor/TagEditor';
import { SaveStatusPill, type SaveStatus } from '../SaveStatusPill/SaveStatusPill';
import { ActionsCard, type Role } from '../ActionsCard/ActionsCard';
import { MatchCard } from '../MatchCard/MatchCard';
import { parseSearchParams } from '../../../lib/parseSearchParams';
import { cn } from '../../../lib/cn';
import styles from './DocumentScreen.module.css';

/** Characters that are illegal in filenames across Windows, macOS, and Linux. */
const FILENAME_ILLEGAL_RE = /[/\\:*?"<>|]/g;

/** Safe "<title>.pdf" download name; "Document <id>.pdf" if the title sanitises to nothing. */
function toDownloadFilename(title: string | null, id: number): string {
  const sanitised = (title ?? '').replace(FILENAME_ILLEGAL_RE, '').trim();
  return sanitised.length > 0 ? `${sanitised}.pdf` : `Document ${id}.pdf`;
}

export type { Role };

export interface DocumentScreenProps {
  document: LibraryDocument;
  /** Which screen opened this document. */
  parent: 'library' | 'search';
  /**
   * Parent URL search string (e.g. "?tag=12" or "?q=invoice"), kept verbatim on
   * the breadcrumb link so the parent's state is restored.
   */
  parentSearch: string;
  /** Admins can edit and delete, members can edit, readonly users only view. */
  role: Role;
}

/**
 * Every edit goes through one `useUpdateDocument` mutation, whose lifecycle
 * drives the `SaveStatusPill`. A successful delete navigates back to the
 * breadcrumb target.
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

  const qc = useQueryClient();
  const canEdit = role !== 'readonly';

  // The last attempted patch, so the retry button can re-fire it.
  const lastAttemptRef = React.useRef<{ id: number; patch: Parameters<typeof update.mutate>[0]['patch'] } | null>(null);

  /**
   * Drops a save while another is in flight: both are built from render-time
   * snapshots, so the second would clobber the first (e.g. a tag edit during a
   * pending title save would write back the old title).
   */
  function mutate(args: Parameters<typeof update.mutate>[0]): void {
    if (update.isPending) return;
    lastAttemptRef.current = args;
    update.mutate(args);
  }

  // Return the pill to idle 2 s after a successful save.
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

  const { query: parentQuery, filters: parentFilters } = React.useMemo(
    () => parseSearchParams(parentSearch),
    [parentSearch],
  );

  // `document.tags` holds names; TagEditor works on ids.
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

  function commitTitle(next: string): void {
    mutate({ id: document.id, patch: { title: next === '' ? null : next } });
  }

  function addTag(id: number): void {
    mutate({ id: document.id, patch: { tags: [...currentTagIds, id] } });
  }

  function removeTag(id: number): void {
    mutate({ id: document.id, patch: { tags: currentTagIds.filter((t) => t !== id) } });
  }

  function createTagThenAdd(name: string): void {
    createTag.mutate(name, {
      onSuccess: (created) => {
        // Read the latest cached document, not the captured `currentTagIds`: two
        // quick creates would otherwise each overwrite the other's tag.
        const latest = qc.getQueryData<{ id: number; tags: string[] }>(['document', document.id]);
        const latestTagIds = ((latest?.tags ?? document.tags) as string[])
          .map((tagName) => tagsByName.get(tagName)?.id)
          .filter((id): id is number => id !== undefined);
        mutate({ id: document.id, patch: { tags: [...latestTagIds, created.id] } });
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
          <SaveStatusPill
            status={saveStatus}
            onRetry={() => {
              if (lastAttemptRef.current !== null) mutate(lastAttemptRef.current);
            }}
          />
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

      <DocumentActions
        className={cn(styles['actions'])}
        pdfUrl={documentPdfUrl(document.id)}
        downloadFilename={toDownloadFilename(document.title, document.id)}
        paperlessUrl={document.paperless_url}
      />

      <div className={styles['grid']}>
        <PdfViewerCard
          documentId={document.id}
          title={document.title ?? `Document ${document.id}`}
          paperlessUrl={document.paperless_url}
          downloadFilename={toDownloadFilename(document.title, document.id)}
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
            onPatch={(patch) => mutate({ id: document.id, patch })}
            onCreateCorrespondent={(name) =>
              createCorrespondent.mutate(name, {
                onSuccess: (created) =>
                  mutate({
                    id: document.id,
                    patch: { correspondent_id: created.id },
                  }),
              })
            }
            onCreateDocumentType={(name) =>
              createDocumentType.mutate(name, {
                onSuccess: (created) =>
                  mutate({
                    id: document.id,
                    patch: { document_type_id: created.id },
                  }),
              })
            }
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
                  /* TODO(VR): show a success toast */
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
