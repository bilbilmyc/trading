import { useEffect, useState } from "react";
import { History, RefreshCw } from "lucide-react";

import { api } from "../api";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ExpandModal } from "../components/ExpandModal";
import { KPIHero } from "../components/KPIHero";
import { PageHeader } from "../components/PageHeader";
import { Sparkline } from "../components/Sparkline";
import { useExpandable } from "../hooks/useExpandable";

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
  const all = useExpandable();

  const VISIBLE_COUNT = 8;

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
    <div className="page page--trade-history stack">
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

      {/* KPI strip — performance summary. */}
      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label="成交笔数"
          value={String(trades.length)}
          icon={<History size={12} />}
          iconGradient="indigo"
          delta={{
            value: `${wins + losses}/${trades.length}`,
            tone: "muted",
          }}
          sparkline={[3, 5, 4, 6, 8, 7, 9, 10]}
        />
        <KPIHero
          label="总盈亏"
          value={formatPnl(totalPnl)}
          icon={<History size={12} />}
          iconGradient={totalPnl > 0 ? "green" : "red"}
          delta={{ value: totalPnl > 0 ? "+" : "" + `${((totalPnl / 1000) * 100).toFixed(1)}%`, tone: totalPnl > 0 ? "positive" : "negative" }}
          sparkline={[0, 1, 2, 4, 3, 5, 7, 8]}
        />
        <KPIHero
          label="盈利 / 亏损"
          value={`${wins} / ${losses}`}
          icon={<History size={12} />}
          iconGradient="cyan"
          sparkline={[5, 5, 6, 4, 7, 5, 8, 7]}
          hint="Win / Loss"
        />
        <KPIHero
          label="胜率"
          value={trades.length > 0 ? `${((wins / trades.length) * 100).toFixed(1)}%` : "--"}
          icon={<History size={12} />}
          iconGradient={trades.length > 0 && wins / trades.length > 0.5 ? "green" : "yellow"}
          sparkline={[0.5, 0.55, 0.6, 0.58, 0.62, 0.65, 0.6, 0.68]}
          hint={`平均 PnL ${formatPnl(trades.length ? totalPnl / trades.length : 0)}`}
        />
      </div>

      {/* (old 6-tile grid removed — replaced by KPIStrip above) */}

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

      <Card
        title="成交明细"
        subtitle={`共 ${trades.length} 笔 · 显示前 ${Math.min(VISIBLE_COUNT, trades.length)}`}
      >
        {error ? <div className="notice notice--error">{error}</div> : null}
        {trades.length === 0 && !loading ? (
          <div className="empty-state">
            <strong>暂无成交记录</strong>
            <span>启动策略后会自动记录,这里按时间倒序</span>
          </div>
        ) : (
          <>
            <div className="scroll-cap scroll-cap--md">
              <DataTable
                columns={columns}
                rows={trades.slice(0, VISIBLE_COUNT)}
                rowKey={(t) => t.order_id}
                rowVariant="compact"
              />
            </div>
            <div className="expandable-foot">
              <span className="expandable-foot__count">
                {trades.length > VISIBLE_COUNT
                  ? `隐藏 ${trades.length - VISIBLE_COUNT} 笔`
                  : "已显示全部"}
              </span>
              {trades.length > VISIBLE_COUNT ? (
                <button type="button" className="expandable-link" onClick={all.open}>
                  展开全部 ({trades.length}) ↗
                </button>
              ) : null}
            </div>
          </>
        )}
      </Card>

      <ExpandModal
        isOpen={all.isOpen}
        onClose={all.close}
        title="全部成交明细"
        subtitle={`共 ${trades.length} 笔 · 按时间倒序`}
      >
        <DataTable
          columns={columns}
          rows={trades}
          rowKey={(t) => t.order_id}
        />
      </ExpandModal>
    </div>
  );
}
