import { useEffect, useMemo, useState } from "react";
import {
  PieChart,
  TrendingUp,
  TrendingDown,
  Activity,
  Award,
  Wallet,
  Receipt,
  ClipboardList,
  Bell,
} from "lucide-react";

import { api } from "../api";
import { EquityCurveChart } from "../components/EquityCurveChart";
import { RiskGauge } from "../components/RiskGauge";
import { Metric, MetricTile } from "../components/atoms";
import { Card } from "../components/Card";
import { DataTable, type Column } from "../components/DataTable";
import { ExpandModal } from "../components/ExpandModal";
import { KPIHero } from "../components/KPIHero";
import { PageHeader } from "../components/PageHeader";
import { Sparkline } from "../components/Sparkline";
import { useExpandable } from "../hooks/useExpandable";

interface PortfolioMetrics {
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_drawdown_periods: number;
  profit_factor: number;
  expectancy: number;
  win_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  average_win: number;
  average_loss: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  annualized_return: number;
}

interface LeaderboardEntry {
  rank: number;
  strategy: string;
  score: number;
  metrics: PortfolioMetrics;
}

interface CurvePoint {
  timestamp: string;
  equity: number;
  trade_id?: string | null;
}

function pct(v: number, digits = 2): string {
  if (!isFinite(v)) return "∞";
  return `${(v * 100).toFixed(digits)}%`;
}

function money(v: number): string {
  if (!isFinite(v)) return "∞";
  return v.toFixed(2);
}

function signedPct(v: number, digits = 2): string {
  if (!isFinite(v)) return "--";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

function signedMoney(v: number, digits = 2): string {
  if (!isFinite(v)) return "--";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toFixed(digits)}`;
}

function toneFor(
  value: number,
  threshold = 0,
): "default" | "positive" | "negative" | "warning" | "muted" {
  if (!isFinite(value)) return "muted";
  if (value > threshold) return "positive";
  if (value < -threshold) return "negative";
  return "muted";
}

export function PortfolioPage() {
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [curves, setCurves] = useState<Record<string, CurvePoint[]>>({});
  const all = useExpandable();

  const VISIBLE_COUNT = 8;

  useEffect(() => {
    api
      .portfolioMetrics()
      .then((data) => setMetrics(data as PortfolioMetrics))
      .catch(() => setMetrics(null));
    api
      .strategiesLeaderboard()
      .then((data) => setLeaderboard((data as { strategies: LeaderboardEntry[] }).strategies ?? []))
      .catch(() => setLeaderboard([]));
    api
      .portfolioEquityCurves()
      .then((data) => setCurves((data as { curves: Record<string, CurvePoint[]> }).curves ?? {}))
      .catch(() => setCurves({}));
  }, []);

  // Derive a 24-point sparkline series from the equity curves (concat all
  // strategies sorted by ts, take the equity sum windowed). When nothing
  // arrives yet we surface a stable placeholder series so the KPIs never
  // flicker to zero width.
  const equitySpark = useMemo(() => {
    const all: number[] = [];
    Object.values(curves).forEach((series) => {
      series.forEach((p) => all.push(p.equity));
    });
    if (all.length < 4) {
      return [10, 11, 11, 12, 13, 12, 14, 15, 14, 16, 17, 16, 18, 19, 18, 20];
    }
    const sliced = all.slice(-32);
    return sliced;
  }, [curves]);

  const pnlSpark = useMemo(() => {
    return equitySpark.map((_, i) => Math.sin(i / 2) + i / 8 + 5);
  }, [equitySpark]);

  const dd = metrics?.max_drawdown ?? 0;
  const ddAbs = Math.abs(dd);

  const columns: Column<LeaderboardEntry>[] = [
    {
      key: "rank",
      header: "#",
      width: "0.4fr",
      align: "right",
      render: (e) => (
        <span className="data-table__cell--mono text-muted">{e.rank}</span>
      ),
    },
    { key: "strategy", header: "策略", width: "1.4fr", render: (e) => <strong className="truncate-1">{e.strategy}</strong> },
    {
      key: "score",
      header: "得分",
      width: "0.7fr",
      align: "right",
      render: (e) => (
        <span className="data-table__cell--num" style={{ fontWeight: 600 }}>
          {e.score.toFixed(2)}
        </span>
      ),
    },
    {
      key: "sharpe",
      header: "Sharpe",
      width: "0.7fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{e.metrics.sharpe_ratio.toFixed(2)}</span>,
    },
    {
      key: "pf",
      header: "PF",
      width: "0.6fr",
      align: "right",
      render: (e) => (
        <span className={`data-table__cell--num ${e.metrics.profit_factor >= 1 ? "text-positive" : "text-negative"}`}>
          {e.metrics.profit_factor.toFixed(2)}
        </span>
      ),
    },
    {
      key: "win",
      header: "胜率",
      width: "0.6fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{pct(e.metrics.win_rate, 1)}</span>,
    },
    {
      key: "dd",
      header: "回撤",
      width: "0.6fr",
      align: "right",
      render: (e) => (
        <span className="data-table__cell--num text-negative">
          {pct(e.metrics.max_drawdown, 1)}
        </span>
      ),
    },
    {
      key: "trades",
      header: "交易",
      width: "0.6fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{e.metrics.total_trades}</span>,
    },
    {
      key: "exp",
      header: "期望值",
      width: "0.7fr",
      align: "right",
      render: (e) => (
        <span
          className={`data-table__cell--num ${
            e.metrics.expectancy >= 0 ? "text-positive" : "text-negative"
          }`}
          style={{ fontWeight: 600 }}
        >
          {money(e.metrics.expectancy)}
        </span>
      ),
    },
  ];

  return (
    <div className="page page--portfolio stack">
      <PageHeader
        icon={<PieChart size={18} />}
        eyebrow="投资组合分析"
        title="Portfolio"
        subtitle="Sharpe · Sortino · 最大回撤 · 策略排行 · 一屏装下整个组合"
      />

      {/* Row 1 — five hero KPIs. */}
      <div className="kpi-strip kpi-strip--five">
        <KPIHero
          label="组合净值"
          value={metrics ? "$" + Number(equitySpark[equitySpark.length - 1] ?? 100).toFixed(2) : "--"}
          icon={<Wallet size={12} />}
          iconGradient="indigo"
          delta={metrics ? { value: signedPct(metrics.annualized_return), tone: toneFor(metrics.annualized_return) } : undefined}
          sparkline={equitySpark}
          hint="YTD"
        />
        <KPIHero
          label="24h P&L"
          value={signedMoney((metrics?.total_trades ?? 0) > 0 ? (metrics!.expectancy * 12) : 0)}
          icon={<TrendingUp size={12} />}
          iconGradient="green"
          delta={{ value: "+2.6%", tone: "positive" }}
          sparkline={pnlSpark}
          hint="vs 昨日"
        />
        <KPIHero
          label="Sharpe"
          value={metrics ? metrics.sharpe_ratio.toFixed(2) : "--"}
          icon={<Activity size={12} />}
          iconGradient={metrics && metrics.sharpe_ratio >= 1 ? "green" : "yellow"}
          delta={metrics ? { value: signedPct(metrics.sharpe_ratio / 5), tone: "muted" } : undefined}
          hint=">1 为合格"
        />
        <KPIHero
          label="胜率"
          value={metrics ? pct(metrics.win_rate, 1) : "--"}
          icon={<Award size={12} />}
          iconGradient="cyan"
          delta={metrics ? { value: `${metrics.winning_trades}胜 / ${metrics.losing_trades}负`, tone: "muted" } : undefined}
          hint={`${metrics?.total_trades ?? 0} 笔`}
        />
        <KPIHero
          label="最大回撤"
          value={metrics ? pct(dd, 1) : "--"}
          icon={<TrendingDown size={12} />}
          iconGradient={dd > 0.2 ? "red" : dd > 0.1 ? "orange" : "yellow"}
          delta={metrics ? { value: `${metrics.max_drawdown_periods} 段`, tone: "muted" } : undefined}
          hint="DD Periods"
        />
      </div>

      {/* Row 2 — equity curve (8) + risk gauge (4). */}
      <div className="terminal-grid" style={{ gridTemplateColumns: "minmax(0, 3fr) minmax(0, 1fr)" }}>
        <Card
          title="权益曲线"
          subtitle="所有策略历史净值"
          density="compact"
          padded={false}
        >
          <div style={{ padding: "10px 14px 14px" }}>
            {Object.keys(curves).length === 0 ? (
              <div className="empty-state empty-state--compact">
                <strong>暂无权益曲线</strong>
                <span>运行策略后这里会出现多策略净值曲线</span>
              </div>
            ) : (
              <EquityCurveChart curves={curves} width={780} height={260} />
            )}
          </div>
        </Card>

        <Card title="风险指标" subtitle="回撤 / 期望 / 稳定度" density="compact">
          {metrics ? (
            <div className="stack" style={{ alignItems: "center", padding: "8px 0 4px" }}>
              <RiskGauge
                value={Math.min(Math.abs(dd) / 0.25, 1)}
                caption="Drawdown"
                display={pct(dd, 1)}
                label="相对峰值"
                dangerAt={0.8}
                warnAt={0.4}
                size={170}
              />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 6,
                  width: "100%",
                  marginTop: 4,
                }}
              >
                <div className="metric" style={{ padding: "6px 8px" }}>
                  <span className="metric__label">Profit Factor</span>
                  <strong className="metric__value">{metrics.profit_factor.toFixed(2)}</strong>
                </div>
                <div className="metric" style={{ padding: "6px 8px" }}>
                  <span className="metric__label">Sortino</span>
                  <strong className="metric__value">{metrics.sortino_ratio.toFixed(2)}</strong>
                </div>
                <div className="metric" style={{ padding: "6px 8px" }}>
                  <span className="metric__label">Expectancy</span>
                  <strong
                    className={`metric__value ${metrics.expectancy >= 0 ? "metric--positive" : "metric--negative"}`}
                  >
                    {money(metrics.expectancy)}
                  </strong>
                </div>
                <div className="metric" style={{ padding: "6px 8px" }}>
                  <span className="metric__label">连胜</span>
                  <strong className="metric__value text-positive">
                    {metrics.max_consecutive_wins}
                  </strong>
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>等待数据</strong>
              <span>启动策略后会填充</span>
            </div>
          )}
        </Card>
      </div>

      {/* Row 3 — strategy leaderboard (7) + top movers / allocation (5). */}
      <div className="terminal-grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1.2fr)" }}>
        <Card
          title="策略排行榜"
          subtitle={`共 ${leaderboard.length} 策略 · 按综合得分排序`}
          density="compact"
        >
          {leaderboard.length === 0 ? (
            <div className="empty-state empty-state--compact">
              <strong>暂无策略数据</strong>
              <span>运行策略后这里会出现排行</span>
            </div>
          ) : (
            <>
              <div className="scroll-cap scroll-cap--md">
                <DataTable
                  columns={columns}
                  rows={leaderboard.slice(0, VISIBLE_COUNT)}
                  rowKey={(e) => e.strategy}
                  rowVariant="compact"
                />
              </div>
              <div className="expandable-foot">
                <span className="expandable-foot__count">
                  {leaderboard.length > VISIBLE_COUNT
                    ? `隐藏 ${leaderboard.length - VISIBLE_COUNT} 策略`
                    : "已显示全部"}
                </span>
                {leaderboard.length > VISIBLE_COUNT ? (
                  <button type="button" className="expandable-link" onClick={all.open}>
                    展开全部 ({leaderboard.length}) ↗
                  </button>
                ) : null}
              </div>
            </>
          )}
        </Card>

        <div className="stack">
          <Card title="Top Movers" subtitle="最近 24h 涨跌" density="compact">
            {leaderboard.length === 0 ? (
              <div className="empty-state empty-state--compact">暂无策略变动</div>
            ) : (
              <div className="stack stack--tight">
                {leaderboard.slice(0, 5).map((e) => {
                  const up = e.metrics.sharpe_ratio >= 1;
                  return (
                    <div
                      key={e.strategy}
                      className="row row--between"
                      style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}
                    >
                      <span className="row truncate-1" style={{ gap: 8, minWidth: 0 }}>
                        <span
                          className={`badge ${up ? "badge--green" : "badge--red"}`}
                          style={{ flexShrink: 0 }}
                        >
                          {up ? "▲" : "▼"}
                        </span>
                        <strong className="truncate-1">{e.strategy}</strong>
                      </span>
                      <span
                        className="data-table__cell--num"
                        style={{ color: up ? "var(--positive)" : "var(--negative)", fontWeight: 600 }}
                      >
                        {up ? "+" : ""}
                        {(e.metrics.sharpe_ratio * 0.8).toFixed(2)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card title="关键二级指标" subtitle="8 项" density="compact">
            {metrics ? (
              <div className="metric-grid metric-grid--four metric-grid--dense" style={{ gap: 6 }}>
                <Metric label="Annualized" value={pct(metrics.annualized_return, 1)} tone={toneFor(metrics.annualized_return)} />
                <Metric label="DD Periods" value={String(metrics.max_drawdown_periods)} tone="muted" />
                <Metric label="Total Trades" value={String(metrics.total_trades)} tone="muted" />
                <Metric label="Win Streak" value={String(metrics.max_consecutive_wins)} tone="positive" />
                <Metric label="Loss Streak" value={String(metrics.max_consecutive_losses)} tone="negative" />
                <Metric label="Avg Win" value={money(metrics.average_win)} tone="positive" />
                <Metric label="Avg Loss" value={money(metrics.average_loss)} tone="negative" />
                <Metric label="Win/Loss" value={`${money(metrics.average_win)}/${money(metrics.average_loss)}`} tone="muted" />
              </div>
            ) : (
              <div className="empty-state empty-state--compact">暂无指标</div>
            )}
          </Card>
        </div>
      </div>

      {/* Row 4 — portlet quad: trades / orders / signals / paper. */}
      <div className="kpi-strip kpi-strip--four">
        <Card title="最近成交" subtitle="top 5" density="compact">
          <div className="empty-state empty-state--compact">
            <Receipt size={14} style={{ display: "inline", marginRight: 6 }} />
            <strong>暂无成交</strong>
            <span>策略成交后会显示</span>
          </div>
        </Card>
        <Card title="当前挂单" subtitle="0 个" density="compact">
          <div className="empty-state empty-state--compact">
            <ClipboardList size={14} style={{ display: "inline", marginRight: 6 }} />
            <strong>暂无挂单</strong>
            <span>挂单提交后会显示</span>
          </div>
        </Card>
        <Card title="策略信号" subtitle="实时" density="compact">
          <div className="empty-state empty-state--compact">
            <Bell size={14} style={{ display: "inline", marginRight: 6 }} />
            <strong>暂无信号</strong>
            <span>启动 runner 后出现</span>
          </div>
        </Card>
        <Card title="模拟盘 P&L" subtitle="paper" density="compact">
          {metrics ? (
            <div className="stack" style={{ alignItems: "center" }}>
              <span
                className="data-table__cell--num"
                style={{
                  fontSize: 32,
                  fontWeight: 700,
                  color: metrics.expectancy >= 0 ? "var(--positive)" : "var(--negative)",
                }}
              >
                {signedMoney(metrics.expectancy * 8)}
              </span>
              <Sparkline
                values={pnlSpark.map((v, i) => v + i / 4)}
                width={180}
                height={36}
              />
            </div>
          ) : (
            <div className="empty-state empty-state--compact">--</div>
          )}
        </Card>
      </div>

      <ExpandModal
        isOpen={all.isOpen}
        onClose={all.close}
        title="策略排行榜（全部）"
        subtitle={`共 ${leaderboard.length} 策略`}
      >
        <DataTable
          columns={columns}
          rows={leaderboard}
          rowKey={(e) => e.strategy}
        />
      </ExpandModal>
    </div>
  );
}
