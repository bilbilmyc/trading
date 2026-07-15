/**
 * EventsPage — risk / order / position / system 事件的统一时间线。
 *
 * 数据源：`/api/v1/events/recent`，10s 自动刷新。filter tabs 切换
 * category；空状态文案"无事件"对应不同分类。
 *
 * 与 StatusDrawer 的区别：drawer 只显示 SSE 实时流过来的 alert，
 * EventsPage 看的是 SQLite 全量历史（kill switch 触发、信号拒绝、
 * 仓位变化都来自 CompositeObserver / LiveTradingGuard observer）。
 */

import { useEffect, useMemo, useState } from "react";
import { History } from "lucide-react";

import { api } from "../api";
import type { AuditEvent } from "../api/strategies";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { useStatus } from "../contexts/StatusContext";
import { formatNumber } from "../utils/format";

const CATEGORIES: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "risk", label: "风险" },
  { key: "order", label: "订单" },
  { key: "position", label: "持仓" },
  { key: "fill", label: "成交" },
  { key: "cancel", label: "撤单" },
  { key: "system", label: "系统" },
];

const REFRESH_INTERVAL_MS = 10_000;
const EVENT_LIMIT = 200;

function levelTone(level: string): string {
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

function categoryChipClass(c: string): string {
  return `status-drawer__chip status-drawer__chip--cat-${(c ?? "").toLowerCase()}`;
}

export function EventsPage() {
  const { lastRefreshedAt } = useStatus();
  const [filter, setFilter] = useState("all");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      setBusy(true);
      try {
        const opts: Parameters<typeof api.recentEvents>[0] = {
          limit: EVENT_LIMIT,
          minutes: 60,
        };
        if (filter !== "all") opts.category = filter;
        const data = await api.recentEvents(opts);
        if (!cancelled) setEvents(data.events);
      } catch {
        // Silent — the page stays at its previous state.
      } finally {
        if (!cancelled) setBusy(false);
      }
    };
    void tick();
    const id = window.setInterval(tick, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [filter]);

  const count = events.length;

  const summary = useMemo(() => {
    const byLevel: Record<string, number> = { critical: 0, error: 0, warning: 0 };
    for (const e of events) {
      const l = (e.level ?? "info").toLowerCase();
      if (l in byLevel) byLevel[l] += 1;
    }
    return byLevel;
  }, [events]);

  return (
    <div className="page page--events stack">
      <PageHeader
        icon={<History size={18} />}
        eyebrow="事件时间线"
        title="Events"
        subtitle="最近 60 分钟的 audit + risk 事件流 · 10s 自动刷新"
        freshness={{ at: lastRefreshedAt, label: "状态" }}
      />

      {/* Category filter chips. */}
      <div className="events-filters" role="tablist" aria-label="按 category 过滤">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            type="button"
            role="tab"
            aria-selected={filter === c.key}
            className={`events-filter ${filter === c.key ? "events-filter--active" : ""}`}
            onClick={() => setFilter(c.key)}
          >
            {c.label}
          </button>
        ))}
        {busy ? <span className="events-filter__busy">· 刷新中</span> : null}
      </div>

      {/* Severity counters. */}
      <div className="events-summary">
        <span className="events-summary__pill events-summary__pill--crit">
          CRIT ×{summary.critical}
        </span>
        <span className="events-summary__pill events-summary__pill--err">
          ERR ×{summary.error}
        </span>
        <span className="events-summary__pill events-summary__pill--warn">
          WARN ×{summary.warning}
        </span>
        <span className="events-summary__count">{formatNumber(count)} 条</span>
      </div>

      <Card title="时间线" subtitle={`filter = ${filter}`}>
        {events.length === 0 ? (
          <EmptyState
            title="无事件"
            hint={
              filter === "all"
                ? "过去 60 分钟没有记录任何事件"
                : `过去 60 分钟没有 ${filter} 类别的事件`
            }
          />
        ) : (
          <ul className="events-list">
            {events.slice(0, 80).map((e, i) => {
              const ts = e.timestamp ?? "";
              const key = `${ts}-${e.event_type ?? ""}-${i}`;
              return (
                <li
                  key={key}
                  className={`events-list__row ${levelTone(e.level ?? "info")}`}
                >
                  <span className="events-list__time num">{shortTime(ts)}</span>
                  <span className={categoryChipClass(e.category ?? "")}>
                    {e.category ?? "—"}
                  </span>
                  <span className="events-list__type">{e.event_type ?? ""}</span>
                  <span className="events-list__msg">{e.message ?? ""}</span>
                  {e.symbol ? (
                    <span className="events-list__symbol">{e.exchange ?? ""}/{e.symbol}</span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
