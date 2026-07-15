/**
 * StatusDrawer — bottom drawer showing recent monitor alerts live.
 *
 * Collapsed by default (28px bar with the count summary).
 * Click to expand (28vh max-height, scrolling).
 *
 * Data source: `useLiveEvents()` which subscribes to
 * ``/api/v1/stream/events`` over SSE. Replaces the prior 5s polling
 * through EngineContext which was always 0–5s stale.
 *
 * Sort: CRITICAL > ERROR > WARNING > INFO, then most-recent first.
 * Filter: top-bar tabs (All / Critical / Error / Warning) scope which
 * rows render. Counters in the bar always reflect the FULL buffer so
 * the badge stays honest — the user can still see "there are 3 ERRs
 * even if the filter is on Critical".
 *
 * Click a row to expand: reveals exchange / symbol / category /
 * timestamp fields that don't fit in the one-line preview.
 */

import { useMemo, useState } from "react";

import { useLiveEvents, type LiveEvent } from "../hooks/useLiveEvents";

type LevelFilter = "all" | "critical" | "error" | "warning";

const RANK: Record<string, number> = {
  critical: 4,
  error: 3,
  warning: 2,
  info: 1,
};

const LEVELS: { key: LevelFilter; label: string; cls: string }[] = [
  { key: "all", label: "全部", cls: "" },
  { key: "critical", label: "CRIT", cls: "status-drawer__filter--crit" },
  { key: "error", label: "ERR", cls: "status-drawer__filter--err" },
  { key: "warning", label: "WARN", cls: "status-drawer__filter--warn" },
];

function levelOf(e: LiveEvent): string {
  return (e.level ?? "info").toLowerCase();
}

function severityLabel(level: string): string {
  switch (level) {
    case "critical":
      return "CRIT";
    case "error":
      return "ERR";
    case "warning":
      return "WARN";
    default:
      return "INFO";
  }
}

function severityClass(level: string): string {
  switch (level) {
    case "critical":
      return "status-drawer__row--critical";
    case "error":
      return "status-drawer__row--error";
    case "warning":
      return "status-drawer__row--warning";
    default:
      return "";
  }
}

function shortTime(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(11, 19);
}

function eventKey(e: LiveEvent, idx: number): string {
  return `${e.event_type ?? "?"}-${e.timestamp ?? idx}`;
}

export function StatusDrawer() {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<LevelFilter>("all");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const events = useLiveEvents();

  // Sort: severity desc, then newest first.
  const sorted = useMemo<LiveEvent[]>(() => {
    const rank = (e: LiveEvent) => RANK[levelOf(e)] ?? 0;
    return [...events].sort((a, b) => {
      const r = rank(b) - rank(a);
      if (r !== 0) return r;
      return (b.timestamp ?? "").localeCompare(a.timestamp ?? "");
    });
  }, [events]);

  // Badges reflect the FULL buffer (not the filter) so the user can see
  // there's a CRIT/ERR even while looking at the INFO stream.
  const criticalCount = sorted.filter((e) => levelOf(e) === "critical").length;
  const errorCount = sorted.filter((e) => levelOf(e) === "error").length;

  // Apply the active filter for the body rows.
  const visible = useMemo<LiveEvent[]>(() => {
    if (filter === "all") return sorted;
    return sorted.filter((e) => levelOf(e) === filter);
  }, [sorted, filter]);

  return (
    <div
      className={`status-drawer ${open ? "" : "status-drawer--collapsed"}`}
      role="region"
      aria-label="最近告警抽屉"
    >
      <div className="status-drawer__bar">
        <button
          className="status-drawer__bar-title status-drawer__bar-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          type="button"
        >
          {open ? "▾ 收起告警" : "▴ 展开告警"}
        </button>
        <div className="status-drawer__filters" role="tablist" aria-label="按级别过滤">
          {LEVELS.map((lv) => (
            <button
              key={lv.key}
              type="button"
              role="tab"
              aria-selected={filter === lv.key}
              className={`status-drawer__filter ${lv.cls} ${
                filter === lv.key ? "status-drawer__filter--active" : ""
              }`}
              onClick={() => setFilter(lv.key)}
            >
              {lv.label}
            </button>
          ))}
        </div>
        {criticalCount > 0 ? (
          <span className="status-drawer__bar-badge status-drawer__bar-badge--crit">
            CRIT ×{criticalCount}
          </span>
        ) : null}
        {errorCount > 0 ? (
          <span className="status-drawer__bar-badge status-drawer__bar-badge--err">
            ERR ×{errorCount}
          </span>
        ) : null}
        <span className="status-drawer__bar-count">{visible.length} 条</span>
      </div>
      <div className="status-drawer__body">
        {visible.length === 0 ? (
          <div className="status-drawer__row-empty">
            {events.length === 0
              ? "暂无告警 — 系统运行平稳"
              : `当前过滤下无告警（共 ${events.length} 条）`}
          </div>
        ) : (
          visible.map((e, i) => {
            const lvl = levelOf(e);
            const key = eventKey(e, i);
            const expanded = expandedKey === key;
            return (
              <div key={key}>
                <button
                  type="button"
                  className={`status-drawer__row status-drawer__row--clickable ${severityClass(lvl)} ${
                    expanded ? "status-drawer__row--expanded" : ""
                  }`}
                  onClick={() => setExpandedKey(expanded ? null : key)}
                  aria-expanded={expanded}
                >
                  <span
                    className={`status-drawer__row-sev status-drawer__row-sev--${lvl}`}
                  >
                    {severityLabel(lvl)}
                  </span>
                  <span className="status-drawer__row-time">
                    {shortTime(e.timestamp)}
                  </span>
                  {e.category ? (
                    <span
                      className={`status-drawer__chip status-drawer__chip--cat-${e.category.toLowerCase()}`}
                    >
                      {e.category}
                    </span>
                  ) : (
                    <span />
                  )}
                  <span className="status-drawer__row-msg">
                    {e.message ?? ""}
                  </span>
                  <span className="status-drawer__row-type">
                    {e.event_type ?? "system"}
                  </span>
                </button>
                {expanded ? (
                  <div className="status-drawer__row-detail">
                    <Detail label="exchange" value={e.exchange} />
                    <Detail label="symbol" value={e.symbol} />
                    <Detail label="category" value={e.category} />
                    <Detail label="event_type" value={e.event_type} />
                    <Detail label="level" value={e.level} />
                    <Detail label="timestamp" value={e.timestamp} fullWidth />
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function Detail({
  label,
  value,
  fullWidth,
}: {
  label: string;
  value: string | undefined;
  fullWidth?: boolean;
}) {
  return (
    <div
      className={`status-drawer__detail ${
        fullWidth ? "status-drawer__detail--full" : ""
      }`}
    >
      <span className="status-drawer__detail-label">{label}</span>
      <span className="status-drawer__detail-value">{value ?? "—"}</span>
    </div>
  );
}
