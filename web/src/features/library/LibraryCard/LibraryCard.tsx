import React, { useState } from 'react';
import { DocThumb } from '../../../components/primitives/DocThumb/DocThumb';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import { formatShortDate } from '../../../lib/formatDate';
import { thumbKindForDocumentType } from '../../../components/primitives/DocThumb/thumbKind';
import type { LibraryDocument } from '../../../api/types';
import { documentThumbUrl } from '../../../api/client';
import styles from './LibraryCard.module.css';

export interface LibraryCardProps {
  document: LibraryDocument;
  onOpen: (id: number) => void;
  /** 'grid' stacks the thumbnail above the metadata; 'list' puts it in a left column. */
  view?: 'grid' | 'list';
  className?: string;
}

/**
 * Model-name tags (e.g. "gpt-5.4-mini") added by the AI classification step;
 * they mean nothing to a reader, so the card hides them.
 */
const PIPELINE_TAG_PATTERN = /^gpt-|^claude-|^gemini-|^llama-|^mistral-|^ollama-/i;

/** Tag chips shown before the "+N" overflow chip. */
const MAX_VISIBLE_TAGS = 3;

/**
 * A document card for the Library grid or list: the real first-page thumbnail
 * (DocThumb while it loads or if it fails), then correspondent, date, title
 * and chips. The whole card is one button that calls `onOpen`; its name is
 * its visible text, so it needs no aria-label.
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
  const [imageLoaded, setImageLoaded] = useState(false);

  const userTags = document.tags.filter((t) => !PIPELINE_TAG_PATTERN.test(t));
  const visibleTags = userTags.slice(0, MAX_VISIBLE_TAGS);
  const overflowCount = userTags.length - visibleTags.length;

  return (
    <button
      type="button"
      className={cn(styles['card'], view === 'list' && styles['card-list'], className)}
      onClick={() => onOpen(document.id)}
    >
      <div className={styles['preview']}>
        <div className={styles['thumb']}>
          {/* The DocThumb stays underneath so the lazy-load window is never an
           *  empty box; the real image is revealed on load. */}
          <DocThumb
            kind={thumbKindForDocumentType(document.document_type)}
            className={cn(styles['thumb-fallback'] ?? '', !imageFailed && imageLoaded ? styles['thumb-fallback-hidden'] ?? '' : '')}
          />
          {!imageFailed && (
            <img
              src={documentThumbUrl(document.id)}
              alt=""
              className={cn(styles['thumb-img'], !imageLoaded && (styles['thumb-img-loading'] ?? ''))}
              // Sized by CSS tokens in LibraryCard.module.css, not attributes.
              loading="lazy"
              decoding="async"
              onLoad={() => setImageLoaded(true)}
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
          {visibleTags.map((tag) => (
            <Chip key={tag}>{`#${tag}`}</Chip>
          ))}
          {overflowCount > 0 && (
            <Chip>{`+${overflowCount}`}</Chip>
          )}
        </div>
      </div>
    </button>
  );
}

/**
 * Memoised so a grid re-render (e.g. a refetch with no changes) skips every
 * card; LibraryScreen passes a stable `onOpen`.
 */
export const LibraryCard = React.memo(LibraryCardInner);
