import { useEffect, useState } from "react";
import { History, RefreshCw } from "lucide-react";

import { api } from "../api";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { DataTable, type Column } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";

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
  if (pnl === undefined || pnl === null) return "text-muted";
  if (pnl > 0) return "text-positive";
  if (pnl < 0) return "text-negative";
  return "text-muted";
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStrategy, filterExchange]);

  const totalPnl = trades.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  const wins = trades.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const losses = trades.filter((t) => (t.realized_pnl ?? 0) < 0).length;
  const strategies = Array.from(
    new Set(trades.map((t) => t.strategy).filter(Boolean) as string[]),
  );
  const exchanges = Array.from(
    new Set(trades.map((t) => t.exchange).filter(Boolean) as string[]),
  );

  const columns: Column<Trade>[] = [
    {
      key: "time",
      header: "时间",
      width: "1.5fr",
      render: (t) => (
        <span className="data-table__cell--mono" title={t.timestamp ?? ""}>
          {formatTime(t.timestamp ?? t.opened_at ?? "")}
        </span>
      ),
    },
    {
      key: "symbol",
      header: "合约",
      width: "1.2fr",
      render: (t) => (
        <div>
          <strong>{t.symbol}</strong>
          <small className="data-table__cell--muted">
            {t.exchange}
            {t.strategy ? ` · ${t.strategy}` : ""}
          </small>
        </div>
      ),
    },
    {
      key: "side",
      header: "方向",
      width: "0.7fr",
      render: (t) => (
        <span
          className={t.side === "buy" ? "text-positive" : "text-negative"}
          style={{ fontWeight: 600 }}
        >
          {t.side === "buy" ? "买入" : "卖出"}
        </span>
      ),
    },
    {
      key: "qty",
      header: "数量",
      width: "0.8fr",
      align: "right",
      render: (t) => <span className="data-table__cell--num">{t.quantity}</span>,
    },
    {
      key: "price",
      header: "价格",
      width: "0.8fr",
      align: "right",
      render: (t) => (
        <span className="data-table__cell--num">
          {(t.price ?? t.entry_price ?? 0).toFixed(2)}
        </span>
      ),
    },
    {
      key: "pnl",
      header: "盈亏",
      width: "0.8fr",
      align: "right",
      render: (t) => (
        <span className={pnlClass(t.realized_pnl)} style={{ fontWeight: 600 }}>
          {formatPnl(t.realized_pnl)}
        </span>
      ),
    },
    {
      key: "status",
      header: "状态",
      width: "0.7fr",
      render: (t) => <span className="data-table__cell--muted">{t.status}</span>,
    },
  ];

  return (
    <div className="page page--trade-history">
      <PageHeader
        icon={<History size={18} />}
        eyebrow="交易历史"
        title="Trade History"
        subtitle="模拟 / 实盘成交记录 · 按时间倒序"
        actions={
          <button
            type="button"
            className="action action--primary"
            onClick={refresh}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            {loading ? "刷新中..." : "刷新"}
          </button>
        }
      />

      <div className="metric-grid">
        <Metric label="成交笔数" value={String(trades.length)} tone="muted" />
        <Metric
          label="总盈亏"
          value={formatPnl(totalPnl)}
          tone={totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "muted"}
        />
        <Metric label="盈利" value={String(wins)} tone="positive" />
        <Metric label="亏损" value={String(losses)} tone="negative" />
        <Metric
          label="胜率"
          value={trades.length > 0 ? `${((wins / trades.length) * 100).toFixed(1)}%` : "--"}
          tone="muted"
        />
      </div>

      <Card title="筛选" subtitle="按策略 / 交易所过滤">
        <div className="form-grid form-grid--inline">
          <label className="field">
            <span>策略</span>
            <select value={filterStrategy} onChange={(e) => setFilterStrategy(e.target.value)}>
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
            <select value={filterExchange} onChange={(e) => setFilterExchange(e.target.value)}>
              <option value="">全部</option>
              {exchanges.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      <Card title="成交明细" subtitle={`${trades.length} 笔`}>
        {error ? <div className="notice notice--error">{error}</div> : null}
        {trades.length === 0 && !loading ? (
          <div className="empty-state">暂无成交记录 — 启动策略后自动记录</div>
        ) : (
          <DataTable
            columns={columns}
            rows={trades}
            rowKey={(t) => t.order_id}
          />
        )}
      </Card>
    </div>
  );
}
