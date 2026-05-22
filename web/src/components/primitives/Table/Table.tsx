import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './Table.module.css';

/** Horizontal alignment of a column's header and cells. */
export type ColumnAlign = 'start' | 'end';

/**
 * One column of a {@link Table}.
 *
 * `key` is a stable identifier for React keys and is not displayed. `header`
 * is the (possibly empty) header label. `render` produces the cell content
 * for a given row — the table never reads row fields itself, so a column can
 * compose any markup (badges, buttons, links).
 *
 * @typeParam Row - the shape of one data row.
 */
export interface Column<Row> {
  /** Stable column identifier — used for React keys, never displayed. */
  key: string;
  /** Header label. May be an empty string (e.g. an actions column). */
  header: string;
  /** Optional fixed column width — any CSS width string (e.g. '120px'). */
  width?: string;
  /** Horizontal alignment of this column. Defaults to 'start'. */
  align?: ColumnAlign;
  /** Cell renderer — receives the row, returns the cell content. */
  render: (row: Row) => React.ReactNode;
}

export interface TableProps<Row> {
  /** Column configuration, left-to-right. */
  columns: Column<Row>[];
  /** The data rows. */
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
  /** Additional class names to merge onto the `<table>`. */
  className?: string;
}

/**
 * Reusable column-configured data table.
 *
 * Renders a semantic `<table>` — header row from `columns`, one body row per
 * item in `rows`, each cell produced by the column's `render`. Screen readers
 * announce it as a real table. When `rows` is empty a single centred
 * `emptyMessage` row is shown instead.
 *
 * The table holds no domain knowledge: callers pass columns whose `render`
 * functions compose whatever markup a cell needs. Used by the Users list and
 * the API-keys list.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function Table<Row>({
  columns,
  rows,
  getRowKey,
  isRowMuted,
  emptyMessage = 'Nothing to show.',
  className,
}: TableProps<Row>): React.ReactElement {
  return (
    <div className={styles['wrapper']}>
      <table className={cn(styles['table'], className)}>
        <thead className={styles['head']}>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  styles['headCell'],
                  col.align === 'end' && styles['headCellEnd'],
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
              <td className={styles['emptyCell']} colSpan={columns.length}>
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
                      col.align === 'end' && styles['cellEnd'],
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
