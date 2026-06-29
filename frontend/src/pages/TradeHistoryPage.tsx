import { useEffect, useState } from "react";

import { api } from "../api";
import { Metric, SectionTitle } from "../components/atoms";

interface Trade {
  order_id: string;
  id?: string;
  strategy?: string;
  exchange: string;
  symbol: string;
  side: string;
  quantity: number;
  price?: number;
  entry_price?: number;
  exit_price?: number | null;
  fee?: number;
  realized_pnl?: number;
  pnl?: number;
  status: string;
  timestamp?: string;
  opened_at?: string;
  closed_at?: string | null;
}

function pnlClass(pnl: number | undefined): string {
  if (pnl === undefined || pnl === null) return "";
  if (pnl > 0) return "text-positive";
  if (pnl < 0) return "text-negative";
  return "";
}

function formatPnl(pnl: number | undefined): string {
  if (pnl === undefined || pnl === null) return "--";
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}${pnl.toFixed(2)}`;
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function TradeHistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterStrategy, setFilterStrategy] = useState("");
  const [filterExchange, setFilterExchange] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const params: { limit?: number; strategy?: string; exchange?: string } = { limit: 200 };
      if (filterStrategy) params.strategy = filterStrategy;
      if (filterExchange) params.exchange = filterExchange;
      const data = await api.tradeHistory(params);
      setTrades((data as { trades: Trade[] }).trades ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载交易历史失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [filterStrategy, filterExchange]);

  // Summary stats
  const totalPnl = trades.reduce(
    (sum, t) => sum + (t.realized_pnl ?? 0),
    0
  );
  const wins = trades.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const losses = trades.filter((t) => (t.realized_pnl ?? 0) < 0).length;
  const strategies = Array.from(new Set(trades.map((t) => t.strategy).filter(Boolean) as string[]));
  const exchanges = Array.from(new Set(trades.map((t) => t.exchange).filter(Boolean) as string[]));

  return (
    <div className="page page--trade-history">
      <header className="page__header">
        <div>
          <p className="eyebrow">交易历史</p>
          <h1>Trade History</h1>
          <span className="page__subtitle">模拟 / 实盘成交记录 · 按时间倒序</span>
        </div>
        <button
          className="action action--primary"
          onClick={refresh}
          disabled={loading}
        >
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      <div className="metric-grid">
        <Metric
          label="成交笔数"
          value={String(trades.length)}
          tone="muted"
        />
        <Metric
          label="总盈亏"
          value={formatPnl(totalPnl)}
          tone={totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "muted"}
        />
        <Metric
          label="盈利"
          value={String(wins)}
          tone="positive"
        />
        <Metric
          label="亏损"
          value={String(losses)}
          tone="negative"
        />
        <Metric
          label="胜率"
          value={
            trades.length > 0
              ? `${((wins / trades.length) * 100).toFixed(1)}%`
              : "--"
          }
          tone="muted"
        />
      </div>

      <section className="panel">
        <SectionTitle title="筛选" subtitle="按策略 / 交易所过滤" />
        <div className="form-grid form-grid--inline">
          <label className="field">
            <span>策略</span>
            <select
              value={filterStrategy}
              onChange={(e) => setFilterStrategy(e.target.value)}
            >
              <option value="">全部</option>
              {strategies.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>交易所</span>
            <select
              value={filterExchange}
              onChange={(e) => setFilterExchange(e.target.value)}
            >
              <option value="">全部</option>
              {exchanges.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="panel">
        <SectionTitle title="成交明细" subtitle={`${trades.length} 笔`} />
        {error && <div className="notice notice--error">{error}</div>}
        {trades.length === 0 && !loading ? (
          <div className="empty-state">
            暂无成交记录 — 启动策略后自动记录
          </div>
        ) : (
          <div className="trade-history">
            <div className="trade-history__row trade-history__row--head">
              <span>时间</span>
              <span>合约</span>
              <span>方向</span>
              <span>数量</span>
              <span>价格</span>
              <span>盈亏</span>
              <span>状态</span>
            </div>
            {trades.map((t) => (
              <div
                key={t.order_id}
                className="trade-history__row lift-hover"
              >
                <span className="trade-history__cell" title={t.timestamp ?? ""}>
                  {formatTime(t.timestamp ?? t.opened_at ?? "")}
                </span>
                <span className="trade-history__cell">
                  <strong>{t.symbol}</strong>
                  <small style={{ color: "var(--text-muted)", display: "block", fontSize: 10 }}>
                    {t.exchange} {t.strategy && `· ${t.strategy}`}
                  </small>
                </span>
                <span
                  className="trade-history__cell"
                  style={{
                    color:
                      t.side === "buy" ? "var(--positive)" : "var(--negative)",
                    fontWeight: 600,
                  }}
                >
                  {t.side === "buy" ? "买入" : "卖出"}
                </span>
                <span className="trade-history__cell">{t.quantity}</span>
                <span className="trade-history__cell">
                  {(t.price ?? t.entry_price ?? 0).toFixed(2)}
                </span>
                <span className={`trade-history__cell ${pnlClass(t.realized_pnl)}`}
                  style={{ fontWeight: 600 }}
                >
                  {formatPnl(t.realized_pnl)}
                </span>
                <span
                  className="trade-history__cell"
                  style={{
                    color: "var(--text-muted)",
                    fontSize: 11,
                  }}
                >
                  {t.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
