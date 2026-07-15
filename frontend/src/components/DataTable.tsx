import type { ReactNode } from "react";

export interface Column<T> {
  /** Stable key — also used as React key fallback. */
  key: string;
  /** Header text. */
  header: string;
  /** CSS grid track value, e.g. "120px" / "1fr" / "minmax(80px,1fr)". */
  width?: string;
  /** Horizontal alignment for both head cell and body cells. */
  align?: "left" | "right" | "center";
  /** Render the cell value for the given row. */
  render: (row: T, index: number) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  /** Stable id for each row (used as React key). */
  rowKey: (row: T, index: number) => string;
  /** Optional click handler per row. */
  onRowClick?: (row: T) => void;
  /** Rendered when rows is empty. Defaults to a simple "暂无数据" message. */
  empty?: ReactNode;
  /** Extra class on the wrapper (e.g. for grid tuning). */
  className?: string;
  /** Optional modifier added to every body row. "compact" -> tighter padding. */
  rowVariant?: "default" | "compact";
}

const DEFAULT_EMPTY = (
  <div className="data-table__empty">
    暂无数据
  </div>
);

/**
 * CSS-grid based table. Replaces the three legacy table implementations
 * (`.leaderboard-table`, `.trade-history__row`, `.data-sources-table__row`)
 * with one configurable component.
 */
export function DataTable<T>({ columns, rows, rowKey, onRowClick, empty, className = "", rowVariant = "default" }: DataTableProps<T>) {
  const template = columns.map((c) => c.width ?? "1fr").join(" ");
  const headStyle = { gridTemplateColumns: template };
  const rowClass =
    rowVariant === "compact" ? "data-table__row data-table__row--compact" : "data-table__row";

  return (
    <div className={`data-table ${className}`}>
      <div className="data-table__head" style={headStyle}>
        {columns.map((c) => (
          <div
            key={c.key}
            className={`data-table__cell data-table__cell--${c.align ?? "left"}`}
          >
            {c.header}
          </div>
        ))}
      </div>
      {rows.length === 0
        ? empty ?? DEFAULT_EMPTY
        : rows.map((row, idx) => (
            <div
              key={rowKey(row, idx)}
              className={`${rowClass} ${onRowClick ? "is-clickable" : ""}`}
              style={headStyle}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <div
                  key={c.key}
                  className={`data-table__cell data-table__cell--${c.align ?? "left"}`}
                >
                  {c.render(row, idx)}
                </div>
              ))}
            </div>
          ))}
    </div>
  );
}
