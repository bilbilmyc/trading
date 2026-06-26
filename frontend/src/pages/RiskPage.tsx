import { useState } from "react";
import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { EmptyState, Metric, SectionTitle } from "../components/atoms";

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

export function RiskPage() {
  const { engine, paper, refresh } = useEngine();
  const { killSwitch, refresh: refreshStatus } = useStatus();
  const [busy, setBusy] = useState(false);

  const risk = engine?.risk;
  const positions = engine?.positions;

  async function toggleKillSwitch() {
    const next = !killSwitch?.enabled;
    if (next && !window.confirm("确认开启全局 Kill Switch？")) return;
    setBusy(true);
    try {
      await api.setKillSwitch(next, next ? "manual_frontend" : "manual_frontend");
      await Promise.all([refresh(), refreshStatus()]);
    } finally {
      setBusy(false);
    }
  }

  async function resetPaper() {
    if (!window.confirm("重置模拟盘？所有 paper 仓位和成交会被清空。")) return;
    await api.resetPaper();
    await refresh();
  }

  return (
    <div className="page page--risk">
      <header className="page__header">
        <div>
          <p className="eyebrow">风控面板</p>
          <h1>Risk</h1>
          <span className="page__subtitle">Kill switch · 风险指标 · 模拟盘 · 持仓</span>
        </div>
      </header>

      <div className="metric-grid">
        <Metric label="每分钟订单" value={`${risk?.orders_last_minute ?? 0}/${risk?.max_orders_per_minute ?? 0}`} tone="muted" />
        <Metric label="当日 PnL" value={`$${formatNumber(risk?.daily_pnl ?? 0)}`} tone={(risk?.daily_pnl ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="当前回撤" value={`${formatNumber((risk?.current_drawdown ?? 0) * 100)}%`} tone={(risk?.current_drawdown ?? 0) > 0.1 ? "warning" : "muted"} />
        <Metric label="活跃仓位" value={String(positions?.active_positions ?? 0)} tone="muted" />
      </div>

      <section className="panel">
        <SectionTitle title="Kill Switch" subtitle="全局闸门" />
        <div className={`kill-switch ${killSwitch?.enabled ? "kill-switch--active" : ""}`}>
          <div>
            <strong>全局 Kill Switch</strong>
            <span>{killSwitch?.enabled ? "已熔断全部真实交易" : "闸门正常"}</span>
          </div>
          <button
            className={`action ${killSwitch?.enabled ? "action--safe" : "action--danger"}`}
            onClick={toggleKillSwitch}
            disabled={busy}
          >
            {busy ? "处理中" : killSwitch?.enabled ? "解除" : "熔断"}
          </button>
        </div>
      </section>

      <section className="panel">
        <SectionTitle title="模拟盘" subtitle="paper account" />
        <div className="metric-grid">
          <Metric label="权益" value={`$${formatNumber(paper?.equity)}`} tone="muted" />
          <Metric label="总盈亏" value={`$${formatNumber(paper?.total_pnl)}`} tone={(paper?.total_pnl ?? 0) >= 0 ? "positive" : "negative"} />
          <Metric label="未实现" value={`$${formatNumber(paper?.unrealized_pnl)}`} tone="muted" />
          <Metric label="持仓" value={String(paper?.active_positions ?? 0)} tone="muted" />
        </div>
        <div className="position-list">
          {paper?.positions.length ? (
            paper.positions.slice(0, 8).map((p) => (
              <div className="position-row" key={`${p.exchange}-${p.symbol}`}>
                <div>
                  <strong>{p.symbol}</strong>
                  <span>{p.exchange}</span>
                </div>
                <div>
                  <strong>{formatNumber(p.quantity, 6)}</strong>
                  <span className={(p.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}>
                    ${formatNumber(p.unrealized_pnl)}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无模拟持仓</EmptyState>
          )}
        </div>
        <button className="action action--ghost" onClick={resetPaper}>
          重置模拟盘
        </button>
      </section>

      <section className="panel">
        <SectionTitle title="本地持仓" subtitle="positions" />
        <div className="position-list">
          {positions?.positions.length ? (
            positions.positions.slice(0, 8).map((p) => (
              <div className="position-row" key={`${p.exchange}-${p.symbol}`}>
                <div>
                  <strong>{p.symbol}</strong>
                  <span>{p.exchange}</span>
                </div>
                <div>
                  <strong>{formatNumber(p.quantity, 6)}</strong>
                  <span className={(p.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}>
                    {formatNumber(p.pnl_pct, 2)}%
                  </span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无本地持仓</EmptyState>
          )}
        </div>
      </section>
    </div>
  );
}