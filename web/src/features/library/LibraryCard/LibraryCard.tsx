import React, { useState } from 'react';
import { DocThumb } from '../../../components/primitives/DocThumb/DocThumb';
import type { DocThumbKind } from '../../../components/primitives/DocThumb/DocThumb';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import type { LibraryDocument } from '../../../api/types';
import { documentThumbUrl } from '../../../api/client';
import styles from './LibraryCard.module.css';

export interface LibraryCardProps {
  /** The document to display. */
  document: LibraryDocument;
  /** Called with the document id when the card is clicked — triggers the
   *  in-app DocumentPreviewScreen overlay in LibraryScreen. */
  onOpen: (id: number) => void;
  /** Additional class names to merge onto the button root. */
  className?: string;
}

/**
 * Map a free-text Paperless document type to one of DocThumb's three page
 * shapes. Substring-matched, case-insensitively: "invoice" -> invoice,
 * "statement"/"payslip" -> statement, everything else -> letter. Mirrors the
 * mapping features/search/SourceCard uses, so a document looks the same
 * shape in search and in the library.
 */
function thumbKindFor(documentType: string | null): DocThumbKind {
  const text = (documentType ?? '').toLowerCase();
  if (text.includes('invoice')) {
    return 'invoice';
  }
  if (text.includes('statement') || text.includes('payslip')) {
    return 'statement';
  }
  return 'letter';
}

/** Short month names for the British D MMM YYYY date format. */
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;

/**
 * Format an ISO-8601 date string as a short British date: 12 Jan 2025.
 *
 * Parsed from the leading YYYY-MM-DD so the result does not drift with the
 * viewer's timezone. Returns an em dash for a null or unparseable value.
 */
function formatDate(iso: string | null): string {
  if (iso === null) {
    return '—';
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (match === null) {
    return '—';
  }
  const year = match[1]!;
  const monthIndex = Number(match[2]) - 1;
  const day = Number(match[3]);
  const month = MONTHS[monthIndex];
  if (month === undefined) {
    return '—';
  }
  return `${day} ${month} ${year}`;
}

/**
 * A single document card for the Library grid/list.
 *
 * The whole card is a button that calls onOpen(document.id); the parent
 * LibraryScreen uses this to set previewDocumentId state, rendering the
 * in-app DocumentPreviewScreen as a full-bleed overlay — the same pattern
 * SearchPage uses for search results. Shows a soft preview area carrying the
 * real first-page thumbnail (proxied from Paperless-ngx), falling back to a
 * stylised DocThumb on error or while loading. Below the preview: a meta
 * block with correspondent · date, a two-line-clamped title, and a row of the
 * document type plus tag chips.
 *
 * Wave 5 is a plain browse — no search-match highlighting.
 *
 * Tier: features/library (CODE_GUIDELINES 12.3) — composes the DocThumb and
 * Chip primitives, the api types, and lib/.
 */
export function LibraryCard({
  document,
  onOpen,
  className,
}: LibraryCardProps): React.ReactElement {
  const title = document.title ?? 'Untitled document';
  const correspondent = document.correspondent ?? 'Unknown sender';
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <button
      type="button"
      className={cn(styles['card'], className)}
      aria-label={`Preview "${title}"`}
      onClick={() => onOpen(document.id)}
    >
      <div className={styles['preview']}>
        <div className={styles['thumb']}>
          {imageFailed ? (
            <DocThumb
              kind={thumbKindFor(document.document_type)}
              className={styles['thumb-fallback'] ?? ''}
            />
          ) : (
            <img
              src={documentThumbUrl(document.id)}
              alt=""
              className={styles['thumb-img']}
              onError={() => setImageFailed(true)}
            />
          )}
        </div>
        <span className={styles['open-affordance']} aria-hidden="true">
          <Icon name="eye" size="small" />
          Preview
        </span>
      </div>

      <div className={styles['meta']}>
        <div className={styles['provenance']}>
          <span className={styles['correspondent']}>{correspondent}</span>
          <span className={styles['dot']} aria-hidden="true">{'·'}</span>
          <span className={styles['date']}>{formatDate(document.created)}</span>
        </div>

        <div className={styles['title']}>{title}</div>

        <div className={styles['spacer']} />

        <div className={styles['chips']}>
          {document.document_type !== null && (
            <Chip>{document.document_type}</Chip>
          )}
          {document.tags.map((tag) => (
            <Chip key={tag}>{`#${tag}`}</Chip>
          ))}
        </div>
      </div>
    </button>
  );
}
