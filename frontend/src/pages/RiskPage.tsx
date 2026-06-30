import { useState } from "react";
import { Shield } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { Metric, MetricTile } from "../components/atoms";
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

  const [localExpanded, setLocalExpanded] = useState(false);
  const [paperExpanded, setPaperExpanded] = useState(false);

  return (
    <div className="page page--risk">
      <PageHeader
        icon={<Shield size={18} />}
        eyebrow="风控面板"
        title="Risk"
        subtitle="Kill switch · 风险指标 · 模拟盘 · 持仓"
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 10,
          marginBottom: 16,
        }}
      >
        <MetricTile
          label="每分钟订单"
          value={`${risk?.orders_last_minute ?? 0}/${risk?.max_orders_per_minute ?? 0}`}
          icon={<i className="fa-solid fa-gauge-high" style={{ fontSize: 16 }} />}
          iconGradient={(risk?.orders_last_minute ?? 0) > (risk?.max_orders_per_minute ?? 1) * 0.8 ? "red" : "indigo"}
        />
        <MetricTile
          label="当日 PnL"
          value={`$${formatNumber(risk?.daily_pnl ?? 0)}`}
          icon={<i className="fa-solid fa-sack-dollar" style={{ fontSize: 16 }} />}
          iconGradient={(risk?.daily_pnl ?? 0) >= 0 ? "green" : "red"}
        />
        <MetricTile
          label="当前回撤"
          value={`${formatNumber((risk?.current_drawdown ?? 0) * 100)}%`}
          icon={<i className="fa-solid fa-arrow-trend-down" style={{ fontSize: 16 }} />}
          iconGradient={(risk?.current_drawdown ?? 0) > 0.1 ? "red" : "yellow"}
        />
        <MetricTile
          label="活跃仓位"
          value={String(positions?.active_positions ?? 0)}
          icon={<i className="fa-solid fa-layer-group" style={{ fontSize: 16 }} />}
          iconGradient="cyan"
        />
      </div>

      {/* Kill Switch (compact) and 模拟盘 (taller) share a row. */}
      <div className="page__grid page__grid--two-thirds">
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
          <div className="metric-grid metric-grid--four metric-grid--dense">
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
            <Metric label="持仓" value={String(paper?.active_positions ?? 0)} tone="muted" />
          </div>
          <div className={`scroll-cap scroll-cap--sm${paperExpanded ? " is-expanded" : ""}`}>
            <div className="position-list">
              {paper?.positions.length ? (
                paper.positions.slice(0, 4).map((p) => (
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
                <div className="empty-state">
                  <strong>暂无模拟持仓</strong>
                  <span>Runner 跑起来后会自动建仓</span>
                </div>
              )}
            </div>
          </div>
          {(paper?.positions.length ?? 0) > 4 ? (
            <div className="expandable-foot">
              <span className="expandable-foot__count">
                隐藏 {paper!.positions.length - 4} 持仓
              </span>
              <button
                type="button"
                className="expandable-link"
                onClick={() => setPaperExpanded((v) => !v)}
              >
                {paperExpanded ? "收起 ↕" : "展开全部 ↕"}
              </button>
            </div>
          ) : null}
          <div>
            <button type="button" className="action action--ghost" onClick={resetPaper}>
              重置模拟盘
            </button>
          </div>
        </Card>
      </div>

      <Card
        title="本地持仓"
        subtitle={`共 ${positions?.positions.length ?? 0} · 显示前 8`}
      >
        {positions?.positions.length === 0 ? (
          <div className="empty-state">
            <strong>暂无本地持仓</strong>
            <span>实盘或模拟下单后会自动出现</span>
          </div>
        ) : (
          <>
            <div className={`scroll-cap scroll-cap--md${localExpanded ? " is-expanded" : ""}`}>
              <div className="position-list">
                {positions?.positions.slice(0, 8).map((p) => (
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
                ))}
              </div>
            </div>
            {(positions?.positions.length ?? 0) > 8 ? (
              <div className="expandable-foot">
                <span className="expandable-foot__count">
                  隐藏 {positions!.positions.length - 8} 持仓
                </span>
                <button
                  type="button"
                  className="expandable-link"
                  onClick={() => setLocalExpanded((v) => !v)}
                >
                  {localExpanded ? "收起 ↕" : "展开全部 ↕"}
                </button>
              </div>
            ) : null}
          </>
        )}
      </Card>

      {error ? <div className="notice notice--error">{error}</div> : null}
      {message ? <div className="notice notice--info">{message}</div> : null}
    </div>
  );
}
