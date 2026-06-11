import React, { useState } from 'react';
import { DocThumb } from '../../../components/primitives/DocThumb/DocThumb';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import { formatShortDate } from '../../../lib/formatDate';
import { thumbKindForDocumentType } from '../../document/thumbKind';
import type { LibraryDocument } from '../../../api/types';
import { documentThumbUrl } from '../../../api/client';
import styles from './LibraryCard.module.css';

export interface LibraryCardProps {
  /** The document to display. */
  document: LibraryDocument;
  /** Called with the document id when the card is clicked — triggers the
   *  in-app DocumentPreviewScreen overlay in LibraryScreen. */
  onOpen: (id: number) => void;
  /** Layout mode — 'grid' (default) stacks thumbnail above metadata;
   *  'list' places the thumbnail as a fixed-width left column. */
  view?: 'grid' | 'list';
  /** Additional class names to merge onto the button root. */
  className?: string;
}

/**
 * A single document card for the Library grid/list.
 *
 * The whole card is a button that calls onOpen(document.id); the parent
 * LibraryScreen routes that to `/library/document/:id`, where the
 * LibraryDocumentPage renders the DocumentPreviewScreen as a full-bleed
 * overlay — making the open preview a shareable URL. Shows a soft preview
 * area carrying the real first-page thumbnail (proxied from Paperless-ngx),
 * falling back to a stylised DocThumb on error or while loading. Below the
 * preview: a meta block with correspondent · date, a two-line-clamped
 * title, and a row of the document type plus tag chips.
 *
 * In `view="grid"` (default) the card stacks thumbnail above metadata.
 * In `view="list"` the thumbnail becomes a fixed-width left column so the
 * row reads as: thumbnail | correspondent · date · title · chips.
 *
 * Wave 5 is a plain browse — no search-match highlighting.
 *
 * Wrapped in `React.memo` so re-renders of the parent grid (e.g. query
 * refetch when no data changed) do not re-render all 24 visible cards.
 * Props are a cache-stable document object + a stable `useCallback` from
 * LibraryScreen + optional className — all shallow-comparable.
 *
 * Tier: features/library (CODE_GUIDELINES 12.3) — composes the DocThumb and
 * Chip primitives, the api types, and lib/.
 */
function LibraryCardInner({
  document,
  onOpen,
  view = 'grid',
  className,
}: LibraryCardProps): React.ReactElement {
  const title = document.title ?? 'Untitled document';
  const correspondent = document.correspondent ?? 'Unknown sender';
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <button
      type="button"
      className={cn(styles['card'], view === 'list' && styles['card-list'], className)}
      aria-label={`Open document: ${title}`}
      onClick={() => onOpen(document.id)}
    >
      <div className={styles['preview']}>
        <div className={styles['thumb']}>
          {imageFailed ? (
            <DocThumb
              kind={thumbKindForDocumentType(document.document_type)}
              className={styles['thumb-fallback'] ?? ''}
            />
          ) : (
            <img
              src={documentThumbUrl(document.id)}
              alt=""
              className={styles['thumb-img']}
              // Fixed dimensions prevent layout shift; the browser reserves
              // the space before the image loads. Values match the CSS tokens:
              // --width-library-thumb (140 px) and --height-library-preview
              // (220 px, cropped via object-fit/max-height in the CSS module).
              width={140}
              height={220}
              loading="lazy"
              decoding="async"
              onError={() => setImageFailed(true)}
            />
          )}
        </div>
        <span className={styles['open-affordance']} aria-hidden="true">
          <Icon name="eye" size="small" />
          View
        </span>
      </div>

      <div className={styles['meta']}>
        <div className={styles['provenance']}>
          <span className={styles['correspondent']}>{correspondent}</span>
          <span className={styles['dot']} aria-hidden="true">{'·'}</span>
          <span className={styles['date']}>{formatShortDate(document.created)}</span>
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

/**
 * Memoised export — the component is `React.memo`'d so the parent grid can
 * re-render (e.g. on query polling) without touching every visible card.
 */
export const LibraryCard = React.memo(LibraryCardInner);
