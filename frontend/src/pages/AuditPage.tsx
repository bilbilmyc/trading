import { useState } from "react";
import { useEngine } from "../contexts/EngineContext";
import { EmptyState, Metric, SectionTitle } from "../components/atoms";

const EVENT_LABELS: Record<string, string> = {
  live_trading_blocked: "实盘守卫拦截",
  kill_switch_enabled: "Kill Switch 开启",
  kill_switch_disabled: "Kill Switch 解除",
  kill_switch_blocked: "Kill Switch 拦截",
  order_rejected_by_risk: "风控拒单",
  live_order_submitted: "策略实盘下单",
  live_order_failed: "策略下单失败",
  paper_order_filled: "纸盘成交",
};

function formatEventType(t: string): string {
  return EVENT_LABELS[t] ?? t.replaceAll("_", " ");
}

const LEVELS = ["all", "critical", "error", "warning", "info"] as const;
type Level = (typeof LEVELS)[number];

export function AuditPage() {
  const { events } = useEngine();
  const [filter, setFilter] = useState<Level>("all");

  const filtered = filter === "all" ? events : events.filter((e) => e.level === filter);

  const byLevel = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.level] = (acc[e.level] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="page page--audit">
      <header className="page__header">
        <div>
          <p className="eyebrow">审计事件</p>
          <h1>Audit</h1>
          <span className="page__subtitle">完整事件流 · 按级别过滤 · 倒序</span>
        </div>
      </header>

      <div className="metric-grid">
        <Metric label="critical" value={String(byLevel.critical ?? 0)} tone="negative" />
        <Metric label="error" value={String(byLevel.error ?? 0)} tone="warning" />
        <Metric label="warning" value={String(byLevel.warning ?? 0)} tone="warning" />
        <Metric label="info" value={String(byLevel.info ?? 0)} tone="muted" />
      </div>

      <div className="filter-row">
        {LEVELS.map((l) => (
          <button
            key={l}
            className={`filter-chip ${filter === l ? "is-active" : ""}`}
            onClick={() => setFilter(l)}
          >
            {l}
          </button>
        ))}
      </div>

      <SectionTitle title="事件流" subtitle={`${filtered.length} 条`} />
      <div className="event-list">
        {filtered.length ? (
          filtered
            .slice()
            .reverse()
            .map((event) => (
              <div className={`event-row event-row--${event.level}`} key={event.id}>
                <div className="event-row__marker" />
                <div>
                  <strong>{formatEventType(event.event_type)}</strong>
                  <span>
                    {event.exchange ?? "--"} · {event.symbol ?? "--"} ·{" "}
                    {new Date(event.timestamp).toLocaleString()}
                  </span>
                  <p>{event.message}</p>
                </div>
              </div>
            ))
        ) : (
          <EmptyState>暂无该级别事件</EmptyState>
        )}
      </div>
    </div>
  );
}