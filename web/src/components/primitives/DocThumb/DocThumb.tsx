import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './DocThumb.module.css';

/**
 * Document-page style — varies the body line-stripe widths so the three
 * common document shapes (a statement, an invoice, a letter) read
 * differently at thumbnail size.
 */
export type DocThumbKind = 'statement' | 'invoice' | 'letter';

export interface DocThumbProps {
  /** Document style — drives the body line-stripe pattern. Defaults to 'statement'. */
  kind?: DocThumbKind;
  /**
   * 0-based body-row indices to draw in the accent colour — the visual
   * "matched chunk" marker. Defaults to no highlighted rows.
   */
  matched?: number[];
  /** Test hook. */
  'data-testid'?: string;
  /** Additional class names to merge onto the wrapper. */
  className?: string;
}

/* Body line-stripe widths per kind. A 0 is a paragraph gap (no stripe). */
const ROWS_BY_KIND: Record<DocThumbKind, number[]> = {
  statement: [70, 60, 0, 80, 75, 78, 70, 65, 0, 50, 80],
  invoice: [70, 50, 0, 80, 80, 76, 72, 68, 0, 86, 0, 60],
  letter: [70, 0, 65, 78, 80, 75, 78, 72, 76, 68, 0, 40],
};

/* SVG geometry — the artboard is authored at this fixed size. */
const VIEW_W = 96;
const VIEW_H = 124;
const BODY_START_Y = 30;
const ROW_HEIGHT = 5;

/**
 * A small SVG mockup of a document page.
 *
 * Purely decorative artwork (the svg is `aria-hidden`): a header block, a
 * hairline rule, a body of grey line-stripes with the `matched` rows drawn in
 * accent blue, and — for statements and invoices — a footer totals band.
 *
 * Used inside `SourceCard` and the document-preview page rail. App-agnostic:
 * it carries no document data, only a `kind` and the matched-row indices.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function DocThumb({
  kind = 'statement',
  matched = [],
  'data-testid': testId,
  className,
}: DocThumbProps): React.ReactElement {
  const rows = ROWS_BY_KIND[kind];
  const hasFooter = kind === 'statement' || kind === 'invoice';
  const matchedSet = new Set(matched);

  return (
    <div className={cn(styles['doc-thumb'], className)} data-testid={testId}>
      <svg
        className={styles['canvas']}
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        {/* Header — title block + sub-line + a logo corner mark */}
        <rect x={8} y={9} width={28} height={4} rx={1} fill="var(--colour-text-primary)" fillOpacity="0.85" />
        <rect x={8} y={16} width={42} height={3} rx={1} fill="var(--colour-text-primary)" fillOpacity="0.35" />
        <rect x={VIEW_W - 22} y={8} width={14} height={14} rx={2} fill="var(--colour-link)" fillOpacity="0.9" />
        <circle cx={VIEW_W - 15} cy={15} r={3} fill="var(--colour-surface)" />

        {/* Hairline under the header */}
        <line x1={8} y1={25} x2={VIEW_W - 8} y2={25} stroke="var(--colour-text-primary)" strokeOpacity="0.08" strokeWidth={0.6} />

        {/* Body line-stripes */}
        {rows.map((width, i) => {
          if (width === 0) {
            return null;
          }
          const isMatched = matchedSet.has(i);
          return (
            <rect
              key={i}
              x={8}
              y={BODY_START_Y + i * ROW_HEIGHT}
              width={width}
              height={2.4}
              rx={1}
              fill={isMatched ? 'var(--colour-accent)' : 'var(--colour-text-primary)'}
              fillOpacity={isMatched ? 0.92 : 0.18}
            />
          );
        })}

        {/* Footer totals band — statements and invoices only */}
        {hasFooter && (
          <g data-doc-footer>
            <line x1={8} y1={VIEW_H - 18} x2={VIEW_W - 8} y2={VIEW_H - 18} stroke="var(--colour-text-primary)" strokeOpacity="0.08" strokeWidth={0.6} />
            <rect x={8} y={VIEW_H - 14} width={32} height={3} rx={1} fill="var(--colour-text-primary)" fillOpacity="0.55" />
            <rect x={VIEW_W - 38} y={VIEW_H - 14} width={30} height={3} rx={1} fill="var(--colour-text-primary)" />
          </g>
        )}
      </svg>
    </div>
  );
}
