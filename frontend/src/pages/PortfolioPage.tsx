import { useEffect, useState } from "react";
import { PieChart, TrendingUp, TrendingDown, Activity, Award } from "lucide-react";

import { api } from "../api";
import { EquityCurveChart } from "../components/EquityCurveChart";
import { Metric, MetricTile } from "../components/atoms";
import { Card } from "../components/Card";
import { DataTable, type Column } from "../components/DataTable";
import { ExpandModal } from "../components/ExpandModal";
import { PageHeader } from "../components/PageHeader";
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

  const columns: Column<LeaderboardEntry>[] = [
    { key: "rank", header: "排名", width: "0.6fr", align: "right", render: (e) => String(e.rank) },
    { key: "strategy", header: "策略", width: "1.4fr", render: (e) => <strong>{e.strategy}</strong> },
    {
      key: "score",
      header: "得分",
      width: "0.8fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{e.score.toFixed(2)}</span>,
    },
    {
      key: "sharpe",
      header: "Sharpe",
      width: "0.8fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{e.metrics.sharpe_ratio.toFixed(2)}</span>,
    },
    {
      key: "win",
      header: "胜率",
      width: "0.7fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{pct(e.metrics.win_rate)}</span>,
    },
    {
      key: "dd",
      header: "回撤",
      width: "0.7fr",
      align: "right",
      render: (e) => (
        <span className="data-table__cell--num text-negative">
          {pct(e.metrics.max_drawdown)}
        </span>
      ),
    },
    {
      key: "trades",
      header: "交易数",
      width: "0.7fr",
      align: "right",
      render: (e) => <span className="data-table__cell--num">{e.metrics.total_trades}</span>,
    },
  ];

  return (
    <div className="page page--portfolio">
      <PageHeader
        icon={<PieChart size={18} />}
        eyebrow="投资组合分析"
        title="Portfolio"
        subtitle="Sharpe · Sortino · 最大回撤 · 策略排行榜"
      />

      {/* 4 hero metrics + 8 secondary metrics. Hero uses MetricTile (AutoClip style);
          secondary uses compact Metric. */}
      <div className="page__grid page__grid--split">
        <Card title="风险调整收益" subtitle="Sharpe / Sortino / Profit Factor / Expectancy">
          {metrics ? (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 10,
                  marginBottom: 12,
                }}
              >
                <MetricTile
                  label="Sharpe"
                  value={metrics.sharpe_ratio.toFixed(2)}
                  icon={<TrendingUp size={16} />}
                  iconGradient={metrics.sharpe_ratio >= 0.5 ? "green" : "yellow"}
                />
                <MetricTile
                  label="Sortino"
                  value={metrics.sortino_ratio.toFixed(2)}
                  icon={<Activity size={16} />}
                  iconGradient={metrics.sortino_ratio >= 0.5 ? "green" : "yellow"}
                />
                <MetricTile
                  label="Profit Factor"
                  value={metrics.profit_factor.toFixed(2)}
                  icon={<Award size={16} />}
                  iconGradient={metrics.profit_factor >= 1.0 ? "green" : "red"}
                />
                <MetricTile
                  label="Expectancy"
                  value={money(metrics.expectancy)}
                  icon={<PieChart size={16} />}
                  iconGradient={metrics.expectancy >= 0 ? "green" : "red"}
                />
              </div>
              <div className="metric-grid metric-grid--four metric-grid--dense">
                <Metric label="Max Drawdown" value={pct(metrics.max_drawdown)} tone="negative" />
                <Metric
                  label="DD Periods"
                  value={String(metrics.max_drawdown_periods)}
                  tone="muted"
                />
                <Metric
                  label="Win Rate"
                  value={pct(metrics.win_rate)}
                  tone={toneFor(metrics.win_rate, 0.5)}
                />
                <Metric
                  label="Annualized"
                  value={pct(metrics.annualized_return)}
                  tone={toneFor(metrics.annualized_return)}
                />
                <Metric label="Total Trades" value={String(metrics.total_trades)} tone="muted" />
                <Metric
                  label="Win Streak"
                  value={String(metrics.max_consecutive_wins)}
                  tone="positive"
                />
                <Metric
                  label="Loss Streak"
                  value={String(metrics.max_consecutive_losses)}
                  tone="negative"
                />
                <Metric
                  label="Avg Win / Loss"
                  value={`${money(metrics.average_win)} / ${money(metrics.average_loss)}`}
                  tone="muted"
                />
              </div>
            </>
          ) : (
            <div className="empty-state">
              <strong>尚无交易历史</strong>
              <span>启动策略或回测后这里会显示风险调整收益</span>
            </div>
          )}
        </Card>

        <Card title="权益曲线" subtitle="各策略历史净值" padded={false}>
          {Object.keys(curves).length === 0 ? (
            <div className="empty-state" style={{ padding: "var(--space-6)" }}>
              暂无权益曲线
            </div>
          ) : (
            <EquityCurveChart curves={curves} width={520} height={280} />
          )}
        </Card>
      </div>

      <Card
        title="策略排行榜"
        subtitle={`共 ${leaderboard.length} 策略 · 按综合得分排序`}
      >
        {leaderboard.length === 0 ? (
          <div className="empty-state">
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
