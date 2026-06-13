import React, { useState } from 'react';
import { cn } from '../../../lib/cn';
import { DocThumb } from '../DocThumb/DocThumb';
import type { DocThumbKind } from '../DocThumb/thumbKind';
import styles from './SourceCardSurface.module.css';

export interface SourceCardSurfaceProps {
  /** 1-based citation index — shown in the badge overlapping the thumbnail. */
  index: number;
  /** Document style for the placeholder DocThumb when no `thumbImageUrl` is
   *  supplied or the image fails to load. */
  thumbKind: DocThumbKind;
  /** When supplied, the real document thumbnail is rendered as an `<img>`.
   *  Falls back to the stylised DocThumb on image error. */
  thumbImageUrl?: string;
  /** 0-based body-row indices to highlight in the placeholder DocThumb. */
  matched?: number[];
  /** When true, lifts the card and adds an accent ring (top-ranked source). */
  highlighted?: boolean;
  /** The card's content column. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The bespoke source-result card shell.
 *
 * A two-column grid — a content column (`children`) and a thumbnail column
 * carrying a `DocThumb` with a circular citation badge overlapping its
 * top-left corner. `highlighted` lifts the card with an accent ring for the
 * top-ranked source. Stacks to one column on narrow viewports.
 *
 * App-agnostic: it knows a citation number and a thumbnail style, nothing
 * about documents. The `SourceCard` feature supplies the content column.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (DocThumb), lib/.
 */
export function SourceCardSurface({
  index,
  thumbKind,
  thumbImageUrl,
  matched = [],
  highlighted = false,
  children,
  className,
}: SourceCardSurfaceProps): React.ReactElement {
  const [imageFailed, setImageFailed] = useState(false);
  const showRealThumb =
    thumbImageUrl !== undefined && thumbImageUrl !== '' && !imageFailed;

  return (
    <article
      className={cn(
        styles['surface'],
        highlighted ? styles['highlighted'] : undefined,
        className,
      )}
    >
      <div className={styles['content']}>{children}</div>
      <div className={styles['thumb']}>
        {showRealThumb ? (
          <img
            src={thumbImageUrl}
            alt=""
            className={styles['thumb-img']}
            onError={() => setImageFailed(true)}
          />
        ) : (
          <DocThumb kind={thumbKind} matched={matched} />
        )}
        <span className={styles['badge']} aria-hidden="true">
          {index}
        </span>
      </div>
    </article>
  );
}
