import React from 'react';
import { Link } from 'react-router-dom';
import type { LibraryDocument } from '../../../api/types';
import { Card } from '../../../components/primitives/Card/Card';
import { DocumentTitle } from '../DocumentTitle/DocumentTitle';
import { PdfViewerCard } from '../PdfViewerCard/PdfViewerCard';
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
  /** Whether the current user may edit the document. Wired up in Wave B. */
  canEdit: boolean;
}

/**
 * Format an ISO-8601 date string to a human-readable form (e.g. "22 May 2026").
 *
 * Returns "No date" for null and preserves the raw string if it cannot be
 * parsed as a valid date.
 */
function formatDocDate(iso: string | null): string {
  if (iso === null) return 'No date';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

/**
 * Full-page composition for a single document — replaces the `DocumentPreviewScreen`
 * overlay flow. Wave A: view-only. Wave B wires up inline title editing and
 * other mutations via the already-stable `canEdit` prop.
 *
 * Layout: centred container with a two-column grid (PDF viewer | details sidebar).
 * Tier: features/document (CODE_GUIDELINES §12.3).
 */
export function DocumentScreen({
  document,
  parent,
  parentSearch,
  canEdit,
}: DocumentScreenProps): React.ReactElement {
  // canEdit is accepted to keep the API stable; wired up in Wave B.
  void canEdit;

  const breadcrumbHref =
    parent === 'library' ? `/library${parentSearch}` : `/${parentSearch}`;
  const breadcrumbLabel = parent === 'library' ? 'Library' : 'Search results';

  return (
    <main className={styles['page']}>
      <Link to={breadcrumbHref} className={styles['crumb']}>
        ← {breadcrumbLabel}
      </Link>

      <div className={styles['title-row']}>
        <DocumentTitle title={document.title} canEdit={canEdit} onChange={() => {}} />
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
          <Card>
            <h3 className={styles['card-h']}>Details</h3>
            <div className={styles['field']}>
              <div className={styles['label']}>Correspondent</div>
              <div className={styles['value']}>{document.correspondent ?? '—'}</div>
            </div>
            <div className={styles['field']}>
              <div className={styles['label']}>Document type</div>
              <div className={styles['value']}>{document.document_type ?? '—'}</div>
            </div>
            <div className={styles['field']}>
              <div className={styles['label']}>Document date</div>
              <div className={styles['value']}>{formatDocDate(document.created)}</div>
            </div>
          </Card>
        </aside>
      </div>
    </main>
  );
}
