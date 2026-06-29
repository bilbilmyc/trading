import { useState } from "react";
import { Shield } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { ListRow } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";
import { formatNumber } from "../utils/format";

export function RiskPage() {
  const { engine, paper, refresh } = useEngine();
  const { killSwitch, refresh: refreshStatus } = useStatus();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const risk = engine?.risk;
  const positions = engine?.positions;

  async function toggleKillSwitch() {
    const next = !killSwitch?.enabled;
    if (next && !window.confirm("确认开启全局 Kill Switch？")) return;
    setBusy(true);
    try {
      await api.setKillSwitch(next, "manual_frontend");
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

  async function closePosition(exchange: string, symbol: string) {
    if (!window.confirm(`确认平仓 ${symbol}（${exchange}）？`)) return;
    setBusy(true);
    try {
      await api.closePosition({ exchange, symbol });
      setMessage(`已平仓 ${symbol}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "平仓失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page page--risk">
      <PageHeader
        icon={<Shield size={18} />}
        eyebrow="风控面板"
        title="Risk"
        subtitle="Kill switch · 风险指标 · 模拟盘 · 持仓"
      />

      <div className="metric-grid">
        <Metric
          label="每分钟订单"
          value={`${risk?.orders_last_minute ?? 0}/${risk?.max_orders_per_minute ?? 0}`}
          tone="muted"
        />
        <Metric
          label="当日 PnL"
          value={`$${formatNumber(risk?.daily_pnl ?? 0)}`}
          tone={(risk?.daily_pnl ?? 0) >= 0 ? "positive" : "negative"}
        />
        <Metric
          label="当前回撤"
          value={`${formatNumber((risk?.current_drawdown ?? 0) * 100)}%`}
          tone={(risk?.current_drawdown ?? 0) > 0.1 ? "warning" : "muted"}
        />
        <Metric
          label="活跃仓位"
          value={String(positions?.active_positions ?? 0)}
          tone="muted"
        />
      </div>

      <Card title="Kill Switch" subtitle="全局闸门">
        <div className={`kill-switch ${killSwitch?.enabled ? "kill-switch--active" : ""}`}>
          <div>
            <strong>全局 Kill Switch</strong>
            <span>{killSwitch?.enabled ? "已熔断全部真实交易" : "闸门正常"}</span>
          </div>
          <button
            type="button"
            className={`action ${killSwitch?.enabled ? "action--safe" : "action--danger"}`}
            onClick={toggleKillSwitch}
            disabled={busy}
          >
            {busy ? "处理中" : killSwitch?.enabled ? "解除" : "熔断"}
          </button>
        </div>
      </Card>

      <Card title="模拟盘" subtitle="paper account">
        <div className="metric-grid">
          <Metric label="权益" value={`$${formatNumber(paper?.equity)}`} tone="muted" />
          <Metric
            label="总盈亏"
            value={`$${formatNumber(paper?.total_pnl)}`}
            tone={(paper?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}
          />
          <Metric
            label="未实现"
            value={`$${formatNumber(paper?.unrealized_pnl)}`}
            tone="muted"
          />
          <Metric
            label="持仓"
            value={String(paper?.active_positions ?? 0)}
            tone="muted"
          />
        </div>
        <div className="position-list">
          {paper?.positions.length ? (
            paper.positions.slice(0, 8).map((p) => (
              <ListRow
                key={`${p.exchange}-${p.symbol}`}
                title={p.symbol}
                subtitle={p.exchange}
                trailing={
                  <div className="list-row__trailing" style={{ flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                    <strong className="data-table__cell--num">
                      {formatNumber(p.quantity, 6)}
                    </strong>
                    <span
                      className={(p.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}
                    >
                      ${formatNumber(p.unrealized_pnl)}
                    </span>
                    <button
                      type="button"
                      className="action action--ghost action--xs"
                      onClick={() => closePosition(p.exchange, p.symbol)}
                      disabled={busy}
                    >
                      平仓
                    </button>
                  </div>
                }
              />
            ))
          ) : (
            <div className="empty-state">暂无模拟持仓</div>
          )}
        </div>
        <button type="button" className="action action--ghost" onClick={resetPaper}>
          重置模拟盘
        </button>
      </Card>

      <Card title="本地持仓" subtitle="positions">
        <div className="position-list">
          {positions?.positions.length ? (
            positions.positions.slice(0, 8).map((p) => (
              <ListRow
                key={`${p.exchange}-${p.symbol}`}
                title={p.symbol}
                subtitle={p.exchange}
                trailing={
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
                    <strong className="data-table__cell--num">
                      {formatNumber(p.quantity, 6)}
                    </strong>
                    <span
                      className={(p.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}
                    >
                      {formatNumber(p.pnl_pct, 2)}%
                    </span>
                  </div>
                }
              />
            ))
          ) : (
            <div className="empty-state">暂无本地持仓</div>
          )}
        </div>
      </Card>

      {error ? <div className="notice notice--error">{error}</div> : null}
      {message ? <div className="notice notice--info">{message}</div> : null}
    </div>
  );
}
