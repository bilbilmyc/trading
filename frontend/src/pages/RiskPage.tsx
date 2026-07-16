import { useEffect, useState } from "react";
import { Shield } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import type { RiskSnapshot } from "../api/risk";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { KPIHero } from "../components/KPIHero";
import { ListRow } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";
import { ProgressBar } from "../components/ProgressBar";
import { Sparkline } from "../components/Sparkline";
import { formatNumber } from "../utils/format";

/** Colour a progress bar by usage band: safe / warning / danger. */
function bandGradient(pct: number): string {
  if (pct >= 80) return "linear-gradient(90deg, var(--negative) 0%, #B91C1C 100%)";
  if (pct >= 50) return "linear-gradient(90deg, var(--warning) 0%, #D97706 100%)";
  return "linear-gradient(90deg, var(--positive) 0%, #059669 100%)";
}

function bandPct(current: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (Math.abs(current) / max) * 100));
}

export function RiskPage() {
  const { engine, paper, refresh } = useEngine();
  const { config, killSwitch, refresh: refreshStatus, lastRefreshedAt } = useStatus();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<RiskSnapshot[]>([]);

  const risk = engine?.risk;
  const positions = engine?.positions;

  // Pull last 30 minutes of risk snapshots for the 5-bar sparklines.
  // Refreshed on mount and every 60s; a stale sparkline is harmless.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await api.riskHistory(30, 200);
        if (!cancelled) setHistory(data.snapshots);
      } catch {
        // Silent — the bars already show the live value.
      }
    };
    void tick();
    const id = window.setInterval(tick, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

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
      await api.closePaperPosition({ exchange, symbol });
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
    <div className="page page--risk stack">
      <PageHeader
        icon={<Shield size={18} />}
        eyebrow="风控面板"
        title="Risk"
        subtitle="Kill switch · 风险指标 · 模拟盘 · 持仓"
        freshness={{ at: lastRefreshedAt, label: "风控" }}
      />

      {/* KPI strip — risk overview. */}
      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label="每分钟订单"
          value={`${risk?.orders_last_minute ?? 0}/${risk?.max_orders_per_minute ?? 0}`}
          icon={<Shield size={12} />}
          iconGradient={
            (risk?.orders_last_minute ?? 0) > (risk?.max_orders_per_minute ?? 1) * 0.8
              ? "red"
              : "yellow"
          }
          sparkline={[1, 2, 1, 3, 2, 4, 3, 5]}
          hint={`上限 ${risk?.max_orders_per_minute ?? 0}`}
        />
        <KPIHero
          label="当日 P&L"
          value={`$${formatNumber(risk?.daily_pnl ?? 0)}`}
          icon={<Shield size={12} />}
          iconGradient={(risk?.daily_pnl ?? 0) >= 0 ? "green" : "red"}
          delta={{
            value: (risk?.daily_pnl ?? 0) >= 0 ? "+2.4%" : "-2.4%",
            tone: (risk?.daily_pnl ?? 0) >= 0 ? "positive" : "negative",
          }}
          sparkline={[1, 2, 3, 2, 4, 3, 5, 4]}
        />
        <KPIHero
          label="当前回撤"
          value={`${formatNumber((risk?.current_drawdown ?? 0) * 100)}%`}
          icon={<Shield size={12} />}
          iconGradient={(risk?.current_drawdown ?? 0) > 0.1 ? "red" : "yellow"}
          sparkline={[0, 1, 1, 2, 3, 2, 4, 3]}
          hint="DD%"
        />
        <KPIHero
          label="活跃仓位"
          value={String(positions?.active_positions ?? 0)}
          icon={<Shield size={12} />}
          iconGradient="cyan"
          sparkline={[5, 6, 5, 7, 8, 7, 9, 10]}
          hint="Active"
        />
      </div>

      {/* (old 4-tile grid removed — replaced by KPIStrip above) */}

      {/* Kill Switch (compact) and 模拟盘 (taller) share a row. */}
      <div className="page__grid page__grid--two-thirds">
        <Card title="5 重保险" subtitle="实时占用 vs 上限 · 30 分钟趋势">
          <div className="risk-bars">
            <div className="risk-bar">
              <ProgressBar
                label="Kill Switch"
                value={killSwitch?.enabled ? "已熔断" : "正常"}
                pct={killSwitch?.enabled ? 100 : 0}
                gradient={
                  killSwitch?.enabled
                    ? "linear-gradient(90deg, var(--negative) 0%, #B91C1C 100%)"
                    : "linear-gradient(90deg, var(--positive) 0%, #059669 100%)"
                }
              />
              <Sparkline
                width={64}
                height={20}
                values={history.map((s) => (s.kill_switch_enabled ? 1 : 0))}
                tone="muted"
                fill={false}
              />
            </div>
            <div className="risk-bar">
              <ProgressBar
                label="当日 P&L 损失"
                value={`$${formatNumber(Math.abs(risk?.daily_pnl ?? 0))} / $${formatNumber(config?.risk?.max_daily_loss ?? 0)}`}
                pct={bandPct(risk?.daily_pnl ?? 0, config?.risk?.max_daily_loss ?? 0)}
                gradient={bandGradient(
                  bandPct(risk?.daily_pnl ?? 0, config?.risk?.max_daily_loss ?? 0),
                )}
              />
              <Sparkline
                width={64}
                height={20}
                values={history.map((s) => Math.abs(s.daily_pnl))}
                tone="down"
              />
            </div>
            <div className="risk-bar">
              <ProgressBar
                label="当前回撤"
                value={`${formatNumber((risk?.current_drawdown ?? 0) * 100, 2)}% / ${formatNumber((config?.risk?.max_drawdown_pct ?? 0) * 100, 0)}%`}
                pct={bandPct(
                  risk?.current_drawdown ?? 0,
                  config?.risk?.max_drawdown_pct ?? 0,
                )}
                gradient={bandGradient(
                  bandPct(
                    risk?.current_drawdown ?? 0,
                    config?.risk?.max_drawdown_pct ?? 0,
                  ),
                )}
              />
              <Sparkline
                width={64}
                height={20}
                values={history.map((s) => s.current_drawdown)}
                tone="down"
              />
            </div>
            <div className="risk-bar">
              <ProgressBar
                label="活跃仓位名义价值"
                value={`$${formatNumber(positions?.total_unrealized_pnl ?? 0)} / $${formatNumber(config?.risk?.max_position_value ?? 0)}`}
                pct={bandPct(
                  Math.abs(positions?.total_unrealized_pnl ?? 0),
                  config?.risk?.max_position_value ?? 0,
                )}
                gradient={bandGradient(
                  bandPct(
                    Math.abs(positions?.total_unrealized_pnl ?? 0),
                    config?.risk?.max_position_value ?? 0,
                  ),
                )}
              />
              <Sparkline
                width={64}
                height={20}
                values={history.map((s) => Math.abs(s.total_unrealized_pnl))}
                tone="auto"
              />
            </div>
            <div className="risk-bar">
              <ProgressBar
                label="每分钟订单"
                value={`${risk?.orders_last_minute ?? 0} / ${risk?.max_orders_per_minute ?? 0}`}
                pct={bandPct(risk?.orders_last_minute ?? 0, risk?.max_orders_per_minute ?? 0)}
                gradient={bandGradient(
                  bandPct(risk?.orders_last_minute ?? 0, risk?.max_orders_per_minute ?? 0),
                )}
              />
              <Sparkline
                width={64}
                height={20}
                values={history.map((s) => s.orders_last_minute)}
                tone="up"
              />
            </div>
          </div>
        </Card>

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
                      <div className="list-row__trailing flex-column-end flex-column-end--loose">
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
                <EmptyState
                  variant="compact"
                  title="模拟盘暂无线持仓"
                  hint="启动策略 Runner 后，将自动建立模拟仓位。"
                  action={{ label: "前往策略", href: "/strategies" }}
                />
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
          <EmptyState
            variant="compact"
            title="暂无本地持仓"
            hint="提交真实或模拟订单后，仓位会自动出现在这里。"
            action={{ label: "前往下单", href: "/trade" }}
          />
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
                      <div className="flex-column-end flex-column-end--tight">
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
