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
 */

import { useMemo, useState } from "react";

import { useLiveEvents, type LiveEvent } from "../hooks/useLiveEvents";

function severityLabel(level?: string): string {
  switch ((level ?? "info").toLowerCase()) {
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

function severityClass(level?: string): string {
  switch ((level ?? "info").toLowerCase()) {
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

const RANK: Record<string, number> = {
  critical: 4,
  error: 3,
  warning: 2,
  info: 1,
};

export function StatusDrawer() {
  const [open, setOpen] = useState(false);
  const events = useLiveEvents();

  const sorted = useMemo<LiveEvent[]>(() => {
    const rank = (e: LiveEvent) => RANK[(e.level ?? "info").toLowerCase()] ?? 0;
    return [...events].sort((a, b) => rank(b) - rank(a));
  }, [events]);

  const recent = sorted.slice(0, 50);
  const criticalCount = recent.filter(
    (e) => (e.level ?? "").toLowerCase() === "critical",
  ).length;
  const errorCount = recent.filter(
    (e) => (e.level ?? "").toLowerCase() === "error",
  ).length;

  return (
    <div
      className={`status-drawer ${open ? "" : "status-drawer--collapsed"}`}
      role="region"
      aria-label="最近告警抽屉"
    >
      <button
        className="status-drawer__bar"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        type="button"
      >
        <span className="status-drawer__bar-title">
          {open ? "▾ 收起告警" : "▴ 展开告警"}
        </span>
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
        <span className="status-drawer__bar-count">{recent.length} 条</span>
      </button>
      <div className="status-drawer__body">
        {recent.length === 0 ? (
          <div className="status-drawer__row-empty">
            暂无告警 — 系统运行平稳
          </div>
        ) : (
          recent.map((e, i) => (
            <div
              key={`${e.event_type ?? "?"}-${e.timestamp ?? i}`}
              className={`status-drawer__row ${severityClass(e.level ?? "")}`}
            >
              <span className={`status-drawer__row-sev status-drawer__row-sev--${(e.level ?? "info").toLowerCase()}`}>
                {severityLabel(e.level ?? "")}
              </span>
              <span>{shortTime(e.timestamp)}</span>
              <span>{e.message ?? ""}</span>
              <span className="status-drawer__row-type">
                {e.event_type ?? "system"}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
