import type {
  CostEstimate,
  FeeRate,
  OpenOrder,
  RecentTrade,
  StrategySignal,
  Ticker,
} from "../api";
import { EmptyState, Metric, SectionTitle } from "./atoms";

function formatNumber(value: number | undefined, digits = 4): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(4)}%`;
}

interface MarketPanelProps {
  symbol: string;
  ticker: Ticker | null;
  trades: RecentTrade[];
  openOrders: OpenOrder[];
  feeRate: FeeRate | null;
  estimate: CostEstimate | null;
  liquidity: "maker" | "taker";
  onLiquidityChange: (liquidity: "maker" | "taker") => void;
  strategyCount: number;
  signalCount: number;
  runnerRunning: boolean;
  onEvaluate: () => void;
  onStartRunner: () => void;
  onStopRunner: () => void;
  onRunOnce: () => void;
  onResetPaper: () => void;
  evaluating: boolean;
  runnerBusy: string;
  signals: StrategySignal[];
  notional: number;
}

export function MarketPanel(props: MarketPanelProps) {
  const change24h = props.ticker?.price_change_pct_24h ?? 0;
  const changeTone = change24h > 0 ? "positive" : change24h < 0 ? "negative" : "muted";

  return (
    <section className="panel panel--market">
      <SectionTitle
        title={`${props.symbol} 行情与成本`}
        subtitle={props.ticker ? `$${formatNumber(props.ticker.last_price)} · 24h` : "等待行情"}
        trailing={<span className="symbol-badge">{props.symbol}</span>}
      />

      <div className="metric-grid">
        <Metric
          label="最新价"
          value={`$${formatNumber(props.ticker?.last_price, 2)}`}
          tone="default"
        />
        <Metric
          label="24h 涨跌"
          value={`${formatNumber(props.ticker?.price_change_pct_24h, 2)}%`}
          tone={changeTone}
        />
        <Metric
          label="24h 成交额"
          value={`$${formatNumber(props.ticker?.quote_volume_24h, 0)}`}
          tone="muted"
        />
        <Metric
          label="名义价值"
          value={`$${formatNumber(props.notional, 2)}`}
          tone="muted"
        />
        <Metric
          label="Maker 费率"
          value={formatPercent(props.feeRate?.maker)}
          tone="muted"
        />
        <Metric
          label="Taker 费率"
          value={formatPercent(props.feeRate?.taker)}
          tone="muted"
        />
        <Metric
          label="预估手续费"
          value={`$${formatNumber(props.estimate?.estimated_fee, 4)}`}
          tone="warning"
          hint={(props.estimate?.liquidity ?? props.liquidity) === "maker" ? "挂单" : "吃单"}
        />
      </div>

      <div className="strategy-bar">
        <div className="strategy-bar__stats">
          <div><span>策略</span><strong>{props.strategyCount}</strong></div>
          <div><span>最近信号</span><strong>{props.signalCount}</strong></div>
          <div>
            <span>运行器</span>
            <strong className={props.runnerRunning ? "text-positive" : "text-muted"}>
              {props.runnerRunning ? "运行中" : "已停止"}
            </strong>
          </div>
        </div>
        <div className="strategy-bar__actions">
          <button className="action action--ghost" onClick={props.onEvaluate} disabled={props.evaluating || !props.symbol}>
            {props.evaluating ? "评估中..." : "评估当前合约"}
          </button>
          <button className="action action--ghost" onClick={props.onStartRunner} disabled={props.runnerRunning || !!props.runnerBusy}>
            启动运行器
          </button>
          <button className="action action--ghost" onClick={props.onStopRunner} disabled={!props.runnerRunning || !!props.runnerBusy}>
            停止运行器
          </button>
          <button className="action action--ghost" onClick={props.onRunOnce} disabled={!!props.runnerBusy}>
            {props.runnerBusy === "once" ? "运行中..." : "手动跑一轮"}
          </button>
          <button className="action action--ghost" onClick={props.onResetPaper} disabled={props.runnerBusy === "paper-reset"}>
            重置模拟盘
          </button>
        </div>
      </div>

      <div className="signals">
        <SectionTitle title="策略信号" subtitle="只观察 · 不自动下单" />
        <div className="signals__list">
          {props.signals.length ? (
            props.signals.slice(0, 6).map((s) => (
              <div className="signal-row" key={`${s.strategy}-${s.symbol}-${s.timestamp}`}>
                <div>
                  <strong>{s.strategy}</strong>
                  <span>{s.symbol}</span>
                </div>
                <div className={s.action === "buy" ? "text-positive" : s.action === "sell" ? "text-negative" : "text-muted"}>
                  <strong>
                    {s.action === "buy" ? "买入" : s.action === "sell" ? "卖出" : "观望"}
                  </strong>
                  <span>{new Date(s.timestamp).toLocaleTimeString()}</span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无策略信号</EmptyState>
          )}
        </div>
      </div>

      <div className="market-lists">
        <div>
          <SectionTitle title="最近成交" subtitle={`${props.trades.length} 条`} />
          <div className="trade-list">
            {props.trades.length ? (
              props.trades.slice(0, 12).map((t) => (
                <div className="trade-row" key={t.trade_id}>
                  <span className={t.side === "buy" ? "tag tag--buy" : "tag tag--sell"}>
                    {t.side === "buy" ? "买" : "卖"}
                  </span>
                  <strong>${formatNumber(t.price, 2)}</strong>
                  <small>{formatNumber(t.quantity, 6)}</small>
                </div>
              ))
            ) : (
              <EmptyState>暂无成交</EmptyState>
            )}
          </div>
        </div>
        <div>
          <SectionTitle title="当前挂单" subtitle={`${props.openOrders.length} 个`} />
          <div className="trade-list">
            {props.openOrders.length ? (
              props.openOrders.slice(0, 8).map((o, i) => (
                <div className="trade-row" key={String(o.order_id ?? o.orderId ?? i)}>
                  <span className="tag tag--neutral">{String(o.side ?? "--")}</span>
                  <strong>${String(o.price ?? "--")}</strong>
                  <small>{String(o.status ?? o.quantity ?? "--")}</small>
                </div>
              ))
            ) : (
              <EmptyState>暂无挂单</EmptyState>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}