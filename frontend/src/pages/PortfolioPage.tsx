import { useEffect, useState } from "react";

import { api } from "../api";
import { EquityCurveChart } from "../components/EquityCurveChart";
import { Metric, SectionTitle } from "../components/atoms";

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

function toneFor(value: number, threshold: number = 0): "default" | "positive" | "negative" | "warning" | "muted" {
  if (!isFinite(value)) return "muted";
  if (value > threshold) return "positive";
  if (value < -threshold) return "negative";
  return "muted";
}

export function PortfolioPage() {
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [curves, setCurves] = useState<Record<string, CurvePoint[]>>({});

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

  return (
    <div className="page page--portfolio">
      <header className="page__header">
        <div>
          <p className="eyebrow">投资组合分析</p>
          <h1>Portfolio</h1>
          <span className="page__subtitle">Sharpe · Sortino · 最大回撤 · 策略排行榜</span>
        </div>
      </header>

      <section className="panel">
        <SectionTitle
          title="风险调整收益"
          subtitle="Sharpe / Sortino / Profit Factor / Expectancy"
        />
        {metrics ? (
          <div className="metric-grid">
            <Metric
              label="Sharpe"
              value={metrics.sharpe_ratio.toFixed(2)}
              tone={toneFor(metrics.sharpe_ratio, 0.5)}
            />
            <Metric
              label="Sortino"
              value={metrics.sortino_ratio.toFixed(2)}
              tone={toneFor(metrics.sortino_ratio, 0.5)}
            />
            <Metric
              label="Profit Factor"
              value={metrics.profit_factor.toFixed(2)}
              tone={toneFor(metrics.profit_factor, 1.0)}
            />
            <Metric
              label="Expectancy"
              value={money(metrics.expectancy)}
              tone={toneFor(metrics.expectancy)}
            />
            <Metric
              label="Max Drawdown"
              value={pct(metrics.max_drawdown)}
              tone="negative"
            />
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
            <Metric
              label="Total Trades"
              value={String(metrics.total_trades)}
              tone="muted"
            />
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
        ) : (
          <div className="empty-state">尚无交易历史 — 启动策略或回测后查看分析</div>
        )}
      </section>

      <section className="panel">
        <SectionTitle
          title="策略排行榜"
          subtitle="按综合得分（Sharpe + 胜率 + 反回撤）排序"
        />
        {leaderboard.length === 0 ? (
          <div className="empty-state">暂无策略数据</div>
        ) : (
          <table className="leaderboard-table">
            <thead>
              <tr>
                <th>排名</th>
                <th>策略</th>
                <th>得分</th>
                <th>Sharpe</th>
                <th>胜率</th>
                <th>回撤</th>
                <th>交易数</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((entry) => (
                <tr key={entry.strategy}>
                  <td>{entry.rank}</td>
                  <td><strong>{entry.strategy}</strong></td>
                  <td>{entry.score.toFixed(2)}</td>
                  <td>{entry.metrics.sharpe_ratio.toFixed(2)}</td>
                  <td>{pct(entry.metrics.win_rate)}</td>
                  <td>{pct(entry.metrics.max_drawdown)}</td>
                  <td>{entry.metrics.total_trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <SectionTitle
          title="权益曲线"
          subtitle="各策略历史净值变化"
        />
        {Object.keys(curves).length === 0 ? (
          <div className="empty-state">暂无权益曲线 — 策略交易后自动记录</div>
        ) : (
          <EquityCurveChart curves={curves} width={960} height={320} />
        )}
      </section>
    </div>
  );
}