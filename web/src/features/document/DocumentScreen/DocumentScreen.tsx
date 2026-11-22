/**
 * Full-page document view: breadcrumb, editable title with save status, the
 * PDF viewer, and a sidebar of metadata, tags and actions.
 */
import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { DocumentPatch, LibraryDocument, TaxonomyItem } from '../../../api/types';
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
import { queryKeys } from '../../../api/hooks/keys';
import { documentPdfUrl, errorDetail } from '../../../api/client';
import { Card } from '../../../components/primitives/Card/Card';
import { Toast, type ToastVariant } from '../../../components/patterns/Toast/Toast';
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
import { isoDateOnly } from '../../../lib/formatDate';
import styles from './DocumentScreen.module.css';

/** Characters that are illegal in filenames across Windows, macOS, and Linux. */
const FILENAME_ILLEGAL_RE = /[/\\:*?"<>|]/g;

/** Safe "<title>.pdf" download name; "Document <id>.pdf" if the title sanitises to nothing. */
function toDownloadFilename(title: string | null, id: number): string {
  const sanitised = (title ?? '').replace(FILENAME_ILLEGAL_RE, '').trim();
  return sanitised.length > 0 ? `${sanitised}.pdf` : `Document ${id}.pdf`;
}

/** Ids for every name, or null if any name is not in `tags`. */
function resolveTagIds(names: string[], tags: TaxonomyItem[]): number[] | null {
  const byName = new Map(tags.map((t) => [t.name, t.id]));
  const ids: number[] = [];
  for (const name of names) {
    const id = byName.get(name);
    if (id === undefined) return null;
    ids.push(id);
  }
  return ids;
}

/** The item's name; null for no item, undefined when the id is not in `items`. */
function nameOf(items: TaxonomyItem[], id: number | null | undefined): string | null | undefined {
  return id === null ? null : items.find((i) => i.id === id)?.name;
}

interface Lists {
  tags: TaxonomyItem[];
  correspondents: TaxonomyItem[];
  documentTypes: TaxonomyItem[];
}

/** The fields of `patch` that `doc` does not show yet. */
function notYetShown(patch: DocumentPatch, doc: LibraryDocument, lists: Lists): DocumentPatch {
  const rest = { ...patch };
  if ('title' in rest && rest.title === doc.title) delete rest.title;
  if ('correspondent_id' in rest && nameOf(lists.correspondents, rest.correspondent_id) === doc.correspondent) {
    delete rest.correspondent_id;
  }
  if ('document_type_id' in rest && nameOf(lists.documentTypes, rest.document_type_id) === doc.document_type) {
    delete rest.document_type_id;
  }
  if ('document_date' in rest && (rest.document_date ?? '') === isoDateOnly(doc.created)) {
    delete rest.document_date;
  }
  if (rest.tags !== undefined) {
    const names = rest.tags.map((id) => nameOf(lists.tags, id));
    if (names.length === doc.tags.length && names.every((n) => n != null && doc.tags.includes(n))) {
      delete rest.tags;
    }
  }
  return rest;
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
 * Every edit goes through one `useUpdateDocument` mutation, one save at a time,
 * whose lifecycle drives the `SaveStatusPill`. A successful delete navigates back to the
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
  // Each toast gets its own key, so a new one starts its own timer and role.
  const [toast, setToast] = React.useState<{ id: number; message: string; variant: ToastVariant } | null>(null);
  const showToast = (message: string, variant: ToastVariant): void =>
    setToast((prev) => ({ id: (prev?.id ?? 0) + 1, message, variant }));
  const notify = (message: string): void => showToast(message, 'info');
  const notifyError = (fallback: string) => (err: Error): void =>
    showToast(errorDetail(err, fallback), 'error');

  // The patch of a failed save; the retry, or the next edit, sends it again.
  const failedRef = React.useRef<DocumentPatch | null>(null);
  const inFlightRef = React.useRef(false);
  // Edits made while a save is in flight, merged so later edits to a field win.
  const pendingRef = React.useRef<DocumentPatch | null>(null);
  // Edits the fetched document does not show yet: shown over it and the base for
  // the next edit, since a save's response and a read right after it come from
  // the search index and may still hold the old values.
  const unsavedRef = React.useRef<DocumentPatch>({});
  const [unsaved, setUnsaved] = React.useState<DocumentPatch>({});
  const keepUnsaved = (next: DocumentPatch): void => {
    unsavedRef.current = next;
    setUnsaved(next);
  };

  function save(patch: DocumentPatch): void {
    keepUnsaved({ ...unsavedRef.current, ...patch });
    const merged = { ...failedRef.current, ...pendingRef.current, ...patch };
    failedRef.current = null;
    if (inFlightRef.current) {
      pendingRef.current = merged;
      return;
    }
    send(merged);
  }

  // mutateAsync, not mutate's callbacks: TanStack skips those after unmount, and
  // an edit queued behind a save must still be sent if the user leaves the page.
  function send(patch: DocumentPatch): void {
    inFlightRef.current = true;
    update.mutateAsync({ id: document.id, patch }).then(
      () => {
        inFlightRef.current = false;
        const next = pendingRef.current;
        pendingRef.current = null;
        if (next !== null) send(next);
      },
      () => {
        inFlightRef.current = false;
        failedRef.current = { ...patch, ...pendingRef.current };
        pendingRef.current = null;
      },
    );
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

  // Once nothing is being saved, drop the edits the fetched document now shows.
  React.useEffect(() => {
    if (inFlightRef.current) return;
    const lists = {
      tags: tags.data ?? [],
      correspondents: correspondents.data ?? [],
      documentTypes: documentTypes.data ?? [],
    };
    const rest = notYetShown(unsavedRef.current, document, lists);
    if (Object.keys(rest).length < Object.keys(unsavedRef.current).length) keepUnsaved(rest);
  }, [document, tags.data, correspondents.data, documentTypes.data, update.status]);

  const shown: LibraryDocument = {
    ...document,
    ...('title' in unsaved ? { title: unsaved.title ?? null } : {}),
    ...('correspondent_id' in unsaved
      ? { correspondent: nameOf(correspondents.data ?? [], unsaved.correspondent_id) ?? null }
      : {}),
    ...('document_type_id' in unsaved
      ? { document_type: nameOf(documentTypes.data ?? [], unsaved.document_type_id) ?? null }
      : {}),
    ...('document_date' in unsaved ? { created: unsaved.document_date ?? null } : {}),
  };
  const shownTagIds = unsaved.tags ?? currentTagIds;

  function commitTitle(next: string): void {
    save({ title: next === '' ? null : next });
  }

  /**
   * A tag patch replaces the whole set, so every tag the document has must
   * resolve to an id first; a stale list is refetched once, and if a name is
   * still unknown nothing is sent rather than dropping that tag.
   */
  function changeTags(change: (ids: number[]) => number[], known: TaxonomyItem[] = []): void {
    // The latest cached document, not the render-time prop: two quick creates
    // would otherwise each overwrite the other's tag.
    const latestNames = (): string[] =>
      qc.getQueryData<LibraryDocument>(queryKeys.document(document.id))?.tags ?? document.tags;
    const send = (ids: number[]): void => {
      save({ tags: change(unsavedRef.current.tags ?? ids) });
    };

    if (unsavedRef.current.tags !== undefined) {
      send(unsavedRef.current.tags);
      return;
    }
    const ids = resolveTagIds(latestNames(), [...(tags.data ?? []), ...known]);
    if (ids !== null) {
      send(ids);
      return;
    }
    void tags.refetch().then((result) => {
      const fresh = resolveTagIds(latestNames(), [...(result.data ?? []), ...known]);
      if (fresh === null) {
        showToast("Couldn't update tags: some of this document's tags are unknown. Reload and try again.", 'error');
        return;
      }
      send(fresh);
    });
  }

  function addTag(id: number): void {
    changeTags((ids) => (ids.includes(id) ? ids : [...ids, id]));
  }

  function removeTag(id: number): void {
    changeTags((ids) => ids.filter((t) => t !== id));
  }

  function createTagThenAdd(name: string): void {
    createTag.mutate(name, {
      onSuccess: (created) => {
        notify(`Created tag “${created.name}”.`);
        changeTags((ids) => [...ids, created.id], [created]);
      },
      onError: notifyError("Couldn't create the tag."),
    });
  }

  return (
    <main className={styles['page']}>
      <Link to={breadcrumbHref} className={styles['crumb']}>
        ← {breadcrumbLabel}
      </Link>

      <div className={styles['title-row']}>
        <DocumentTitle title={shown.title} canEdit={canEdit} onChange={commitTitle} />
        {saveStatus === 'error' ? (
          <SaveStatusPill
            status={saveStatus}
            onRetry={() => save({})}
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
        downloadFilename={toDownloadFilename(shown.title, document.id)}
        paperlessUrl={document.paperless_url}
      />

      <div className={styles['grid']}>
        <PdfViewerCard
          documentId={document.id}
          title={shown.title ?? `Document ${document.id}`}
          paperlessUrl={document.paperless_url}
          downloadFilename={toDownloadFilename(shown.title, document.id)}
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
            document={shown}
            correspondents={correspondents.data ?? []}
            documentTypes={documentTypes.data ?? []}
            canEdit={canEdit}
            onPatch={save}
            onCreateCorrespondent={(name) =>
              createCorrespondent.mutate(name, {
                onSuccess: (created) => {
                  notify(`Created correspondent “${created.name}”.`);
                  save({ correspondent_id: created.id });
                },
                onError: notifyError("Couldn't create the correspondent."),
              })
            }
            onCreateDocumentType={(name) =>
              createDocumentType.mutate(name, {
                onSuccess: (created) => {
                  notify(`Created document type “${created.name}”.`);
                  save({ document_type_id: created.id });
                },
                onError: notifyError("Couldn't create the document type."),
              })
            }
          />

          <Card>
            <h3 className={styles['card-h']}>Tags</h3>
            <TagEditor
              selectedIds={shownTagIds}
              availableTags={tags.data ?? []}
              canEdit={canEdit && tags.data !== undefined}
              onAdd={addTag}
              onRemove={removeTag}
              onCreate={createTagThenAdd}
            />
          </Card>

          <ActionsCard
            documentId={document.id}
            title={shown.title ?? `Document ${document.id}`}
            role={role}
            reclassifying={reclassify.isPending}
            retranscribing={retranscribe.isPending}
            deleting={deleteDoc.isPending}
            onReclassify={(id) =>
              reclassify.mutate(id, {
                onSuccess: () => notify('Queued for re-classification.'),
                onError: notifyError("Couldn't queue re-classification."),
              })
            }
            onRetranscribe={(id) =>
              retranscribe.mutate(id, {
                onSuccess: () => notify('Queued for re-transcription.'),
                onError: notifyError("Couldn't queue re-transcription."),
              })
            }
            onDelete={(id) =>
              deleteDoc.mutate(id, {
                onSuccess: () => navigate(breadcrumbHref),
                onError: notifyError("Couldn't delete the document."),
              })
            }
          />
        </aside>
      </div>

      {toast !== null && (
        <Toast
          key={toast.id}
          message={toast.message}
          variant={toast.variant}
          onDismiss={() => setToast(null)}
          // Errors stay until dismissed so they can be read at any pace.
          {...(toast.variant === 'info' ? { dismissAfterMs: 6_000 } : {})}
        />
      )}
    </main>
  );
}
