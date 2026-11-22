import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Table.module.css';

/** Horizontal alignment of a column's header and cells. */
export type ColumnAlign = 'start' | 'end';

/**
 * One column of a {@link Table}. The table never reads row fields itself;
 * `render` produces each cell, so a column can compose any markup.
 */
export interface Column<Row> {
  /** Stable column identifier — used for React keys, never displayed. */
  key: string;
  /** Header label. May be an empty string, or visually-hidden text (e.g. an actions column). */
  header: React.ReactNode;
  /** Optional fixed column width — any CSS width string (e.g. '120px'). */
  width?: string;
  /** Horizontal alignment of this column. Defaults to 'start'. */
  align?: ColumnAlign;
  render: (row: Row) => React.ReactNode;
}

export interface TableProps<Row> {
  /** Column configuration, left-to-right. */
  columns: Column<Row>[];
  rows: Row[];
  /** Derives a stable React key for a row. */
  getRowKey: (row: Row) => string | number;
  /**
   * Returns true for a row that should render dimmed (e.g. a suspended user
   * or an expired key). Sets `data-muted="true"` on the `<tr>`.
   */
  isRowMuted?: (row: Row) => boolean;
  /** Message shown in place of rows when `rows` is empty. */
  emptyMessage?: string;
  className?: string;
}

/**
 * The browser leaves a control that is only partly clipped where it is, so its
 * focus ring is cut off or sits under the edge fade. The wrapper's
 * scroll-padding holds the fade clear.
 */
function revealFocused(event: React.FocusEvent<HTMLElement>): void {
  event.target.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
}

/**
 * Column-configured semantic `<table>`. When `rows` is empty a single
 * `emptyMessage` row is shown instead.
 */
export function Table<Row>({
  columns,
  rows,
  getRowKey,
  isRowMuted,
  emptyMessage = 'Nothing to show.',
  className,
}: TableProps<Row>): React.ReactElement {
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  const tableRef = React.useRef<HTMLTableElement>(null);
  const [edges, setEdges] = React.useState({ start: false, end: false });

  // Track which edges have more content beyond them so CSS can fade those edges.
  React.useEffect(() => {
    const el = wrapperRef.current;
    if (el === null) return undefined;
    const update = (): void => {
      const start = el.scrollLeft > 1;
      const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
      setEdges((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    // The container and the table change width independently; ResizeObserver is
    // absent in jsdom / SSR, where the one-shot measure above still runs.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(el);
    if (tableRef.current !== null) observer?.observe(tableRef.current);
    return () => {
      el.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, []);

  return (
    <div
      ref={wrapperRef}
      className={styles['wrapper']}
      data-fade-start={edges.start ? 'true' : undefined}
      data-fade-end={edges.end ? 'true' : undefined}
      onFocus={revealFocused}
    >
      <table ref={tableRef} className={cn(styles['table'], className)}>
        <thead className={styles['head']}>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  styles['head-cell'],
                  col.align === 'end' && styles['head-cell-end'],
                )}
                style={col.width !== undefined ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className={styles['empty-cell']} colSpan={columns.length}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={getRowKey(row)}
                className={styles['row']}
                data-muted={isRowMuted?.(row) === true ? 'true' : undefined}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      styles['cell'],
                      col.align === 'end' && styles['cell-end'],
                    )}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
