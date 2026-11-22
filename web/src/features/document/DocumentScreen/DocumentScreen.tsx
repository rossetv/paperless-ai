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
import { RETURN_TO_RESULTS } from '../../search/useStreamingSearch';
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

type Field = 'title' | 'correspondent_id' | 'document_type_id' | 'document_date';

/** What the fetched document shows for a field, as it shows it. */
function fetchedValue(doc: LibraryDocument, field: Field): string | null {
  switch (field) {
    case 'title': return doc.title;
    case 'correspondent_id': return doc.correspondent;
    case 'document_type_id': return doc.document_type;
    case 'document_date': return isoDateOnly(doc.created);
  }
}

/**
 * Edits the fetched document does not show yet. A field keeps the value it had
 * when edited and is dropped once the fetched value moves off it, to ours or to
 * someone else's. Tags are kept as additions and removals over the fetched tags,
 * so a tag another change adds or removes meanwhile is neither hidden nor undone.
 */
interface Layer {
  fields: Partial<Record<Field, { patch: DocumentPatch; base: string | null }>>;
  /**
   * `armed` once the fetched tags have differed from the edit: a tag removed and
   * added back is only settled after a read shows the state in between.
   */
  tags: Map<number, { name: string; add: boolean; armed: boolean }>;
}

const EMPTY_LAYER: Layer = { fields: {}, tags: new Map() };

/** `layer` less what `doc` now shows; the same object when nothing changed. */
function settle(layer: Layer, doc: LibraryDocument): Layer {
  let changed = false;
  const fields = { ...layer.fields };
  for (const field of Object.keys(fields) as Field[]) {
    if (fetchedValue(doc, field) !== fields[field]?.base) {
      delete fields[field];
      changed = true;
    }
  }
  const tags = new Map(layer.tags);
  for (const [id, op] of tags) {
    const shown = doc.tags.includes(op.name) === op.add;
    if (shown && op.armed) {
      tags.delete(id);
      changed = true;
    } else if (!shown && !op.armed) {
      tags.set(id, { ...op, armed: true });
      changed = true;
    }
  }
  return changed ? { fields, tags } : layer;
}

/** `ids` with the layer's removals taken out and its additions put in. */
function applyTagOps(ids: number[], ops: Layer['tags']): number[] {
  const kept = ids.filter((id) => ops.get(id)?.add !== false);
  for (const [id, op] of ops) if (op.add && !kept.includes(id)) kept.push(id);
  return kept;
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

  // The patch of a failed save; the retry, or the next edit, sends it again,
  // its tags rebuilt from the latest ones.
  const failedRef = React.useRef<DocumentPatch | null>(null);
  const inFlightRef = React.useRef(false);
  // Edits made while a save is in flight, merged so later edits to a field win.
  const pendingRef = React.useRef<DocumentPatch | null>(null);
  // Shown over the fetched document and the base for the next edit, since a
  // save's response and a read right after it come from the search index and
  // may still hold the old values.
  const layerRef = React.useRef<Layer>(EMPTY_LAYER);
  const [layer, setLayer] = React.useState<Layer>(EMPTY_LAYER);
  const keepLayer = (next: Layer): void => {
    layerRef.current = next;
    setLayer(next);
  };
  // The latest cached document, not the render-time prop: an edit made right
  // after another must build on what the cache holds now.
  const latestDoc = (): LibraryDocument =>
    qc.getQueryData<LibraryDocument>(queryKeys.document(document.id)) ?? document;

  /** Keeps a field edit in the layer and saves it. */
  function editFields(patch: DocumentPatch): void {
    const fields = { ...layerRef.current.fields };
    for (const field of Object.keys(patch) as Field[]) {
      fields[field] = { patch: { [field]: patch[field] }, base: fields[field]?.base ?? fetchedValue(latestDoc(), field) };
    }
    keepLayer({ ...layerRef.current, fields });
    save(patch);
  }

  function save(patch: DocumentPatch): void {
    const merged = { ...failedRef.current, ...pendingRef.current, ...patch };
    failedRef.current = null;
    if (inFlightRef.current) {
      pendingRef.current = merged;
      return;
    }
    send(merged);
  }

  /** The latest fetched tags with the layer's tag edits applied; null if a name is unknown. */
  function latestTagIds(): number[] | null {
    const ops = layerRef.current.tags;
    const known = [...(tags.data ?? []), ...[...ops].map(([id, op]) => ({ id, name: op.name, document_count: 0 }))];
    const ids = resolveTagIds(latestDoc().tags, known);
    return ids && applyTagOps(ids, ops);
  }

  // mutateAsync, not mutate's callbacks: TanStack skips those after unmount, and
  // an edit queued behind a save must still be sent if the user leaves the page.
  // A tag list stored for later is rebuilt now, so a tag another change made
  // meanwhile is not undone.
  function send(stored: DocumentPatch): void {
    const patch = stored.tags === undefined ? stored : { ...stored, tags: latestTagIds() ?? stored.tags };
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
    const next = settle(layerRef.current, document);
    if (next !== layerRef.current) keepLayer(next);
  }, [document, update.status]);

  const edited = (field: Field): DocumentPatch | undefined => layer.fields[field]?.patch;
  const title = edited('title');
  const correspondent = edited('correspondent_id');
  const documentType = edited('document_type_id');
  const documentDate = edited('document_date');
  const shown: LibraryDocument = {
    ...document,
    ...(title ? { title: title.title ?? null } : {}),
    ...(correspondent
      ? { correspondent: nameOf(correspondents.data ?? [], correspondent.correspondent_id) ?? null }
      : {}),
    ...(documentType
      ? { document_type: nameOf(documentTypes.data ?? [], documentType.document_type_id) ?? null }
      : {}),
    ...(documentDate ? { created: documentDate.document_date ?? null } : {}),
  };
  const shownTagIds = applyTagOps(currentTagIds, layer.tags);

  function commitTitle(next: string): void {
    editFields({ title: next === '' ? null : next });
  }

  /**
   * A tag patch replaces the whole set, so every tag the document has must
   * resolve to an id first; a stale list is refetched once, and if a name is
   * still unknown nothing is sent rather than dropping that tag.
   */
  function changeTag(tag: TaxonomyItem, add: boolean): void {
    const send = (ids: number[]): void => {
      const ops = new Map(layerRef.current.tags);
      ops.delete(tag.id);
      const armed = latestDoc().tags.includes(tag.name) !== add;
      // A removal that undoes an addition leaves the fetched tags in charge: the
      // index may jump straight to the end, so waiting for a read of the tag would
      // hide it for good once another change adds it. A tag added back after a
      // removal still waits, since a read may yet show the removal alone.
      if (armed || add) ops.set(tag.id, { name: tag.name, add, armed });
      keepLayer({ ...layerRef.current, tags: ops });
      save({ tags: applyTagOps(ids, ops) });
    };

    const known = [...(tags.data ?? []), tag];
    const ids = resolveTagIds(latestDoc().tags, known);
    if (ids !== null) {
      send(ids);
      return;
    }
    void tags.refetch().then((result) => {
      if (result.status === 'error') {
        showToast("Couldn't load the tag list, so the tags weren't changed. Try again.", 'error');
        return;
      }
      const fresh = resolveTagIds(latestDoc().tags, [...(result.data ?? []), tag]);
      if (fresh === null) {
        showToast("Couldn't update tags: some of this document's tags are unknown. Reload and try again.", 'error');
        return;
      }
      send(fresh);
    });
  }

  // A tag just created may be on the page before the tag list has it.
  const tagById = (id: number): TaxonomyItem | undefined => {
    const op = layerRef.current.tags.get(id);
    return tags.data?.find((t) => t.id === id) ?? (op && { id, name: op.name, document_count: 0 });
  };

  function addTag(id: number): void {
    const tag = tagById(id);
    if (tag) changeTag(tag, true);
  }

  function removeTag(id: number): void {
    const tag = tagById(id);
    if (tag) changeTag(tag, false);
  }

  // A create already running ignores another press, so a double press makes one.
  function createTagThenAdd(name: string): void {
    if (createTag.isPending) return;
    createTag.mutate(name, {
      onSuccess: (created) => {
        notify(`Created tag “${created.name}”.`);
        changeTag(created, true);
      },
      onError: notifyError("Couldn't create the tag."),
    });
  }

  return (
    <main className={styles['page']}>
      <Link
        to={breadcrumbHref}
        state={parent === 'search' ? RETURN_TO_RESULTS : undefined}
        className={styles['crumb']}
      >
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
            onPatch={editFields}
            onCreateCorrespondent={(name) =>
              !createCorrespondent.isPending &&
              createCorrespondent.mutate(name, {
                onSuccess: (created) => {
                  notify(`Created correspondent “${created.name}”.`);
                  editFields({ correspondent_id: created.id });
                },
                onError: notifyError("Couldn't create the correspondent."),
              })
            }
            onCreateDocumentType={(name) =>
              !createDocumentType.isPending &&
              createDocumentType.mutate(name, {
                onSuccess: (created) => {
                  notify(`Created document type “${created.name}”.`);
                  editFields({ document_type_id: created.id });
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
            onDelete={(id) => deleteDoc.mutateAsync(id).then(() => navigate(breadcrumbHref))}
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
