import { useState } from "react";
import { ClipboardList } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ExpandModal } from "../components/ExpandModal";
import { ListRow, type ListRowLevel } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";
import { useExpandable } from "../hooks/useExpandable";

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

function levelToRowLevel(level: string): ListRowLevel | undefined {
  if (level === "critical" || level === "error" || level === "warning" || level === "info") {
    return level;
  }
  return undefined;
}

export function AuditPage() {
  const { events } = useEngine();
  const [filter, setFilter] = useState<Level>("all");
  const all = useExpandable();
  const VISIBLE_COUNT = 12;

  const filtered = filter === "all" ? events : events.filter((e) => e.level === filter);

  const byLevel = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.level] = (acc[e.level] ?? 0) + 1;
    return acc;
  }, {});

  const reversed = filtered.slice().reverse();

  return (
    <div className="page page--audit stack">
      <PageHeader
        icon={<ClipboardList size={18} />}
        eyebrow="审计事件"
        title="Audit"
        subtitle="完整事件流 · 按级别过滤 · 倒序"
      />

      <div className="metric-grid metric-grid--four">
        <Metric label="critical" value={String(byLevel.critical ?? 0)} tone="negative" />
        <Metric label="error" value={String(byLevel.error ?? 0)} tone="warning" />
        <Metric label="warning" value={String(byLevel.warning ?? 0)} tone="warning" />
        <Metric label="info" value={String(byLevel.info ?? 0)} tone="muted" />
      </div>

      <div className="filter-row">
        {LEVELS.map((l) => (
          <button
            key={l}
            type="button"
            className={`filter-chip ${filter === l ? "is-active" : ""}`}
            onClick={() => setFilter(l)}
          >
            {l}
          </button>
        ))}
      </div>

      <Card
        title="事件流"
        subtitle={`${filtered.length} 条 · 显示前 ${Math.min(VISIBLE_COUNT, filtered.length)}`}
      >
        {filtered.length === 0 ? (
          <EmptyState
            variant="iconic"
            title="暂无该级别事件"
            hint="切到 all 或别的级别查看"
          />
        ) : (
          <>
            <div className="scroll-cap scroll-cap--lg">
              <div className="event-list">
                {reversed.slice(0, VISIBLE_COUNT).map((event) => (
                  <ListRow
                    key={event.id}
                    leading={<span className="event-row__marker" />}
                    level={levelToRowLevel(event.level)}
                    title={formatEventType(event.event_type)}
                    subtitle={`${event.exchange ?? "--"} · ${event.symbol ?? "--"} · ${new Date(
                      event.timestamp,
                    ).toLocaleString()}${event.message ? ` · ${event.message}` : ""}`}
                  />
                ))}
              </div>
            </div>
            <div className="expandable-foot">
              <span className="expandable-foot__count">
                {filtered.length > VISIBLE_COUNT
                  ? `隐藏 ${filtered.length - VISIBLE_COUNT} 条`
                  : "已显示全部"}
              </span>
              {filtered.length > VISIBLE_COUNT ? (
                <button type="button" className="expandable-link" onClick={all.open}>
                  展开全部 ({filtered.length}) ↗
                </button>
              ) : null}
            </div>
          </>
        )}
      </Card>

      <ExpandModal
        isOpen={all.isOpen}
        onClose={all.close}
        title="审计事件 · 全部"
        subtitle={`${filtered.length} 条 · 倒序`}
        toolbar={
          <div className="filter-row" style={{ marginTop: 0 }}>
            {LEVELS.map((l) => (
              <button
                key={l}
                type="button"
                className={`filter-chip ${filter === l ? "is-active" : ""}`}
                onClick={() => setFilter(l)}
              >
                {l}
              </button>
            ))}
          </div>
        }
      >
        <div className="event-list">
          {reversed.map((event) => (
            <ListRow
              key={event.id}
              leading={<span className="event-row__marker" />}
              level={levelToRowLevel(event.level)}
              title={formatEventType(event.event_type)}
              subtitle={`${event.exchange ?? "--"} · ${event.symbol ?? "--"} · ${new Date(
                event.timestamp,
              ).toLocaleString()}${event.message ? ` · ${event.message}` : ""}`}
            />
          ))}
        </div>
      </ExpandModal>
    </div>
  );
}
