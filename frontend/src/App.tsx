import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BadgeDollarSign,
  CircleDot,
  Gauge,
  Power,
  RefreshCw,
  Send,
  ShieldAlert,
  Wifi,
  WifiOff,
} from "lucide-react";

import {
  api,
  ContractOrderPayload,
  CostEstimate,
  EngineStatus,
  ExchangeName,
  FeeRate,
  Intent,
  Liquidity,
  MarginMode,
  PositionSide,
} from "./api";

const EXCHANGE_OPTIONS: Array<{ value: ExchangeName; label: string; symbol: string }> = [
  { value: "okx_swap", label: "OKX Swap", symbol: "BTC-USDT-SWAP" },
  { value: "binance_usdm", label: "Binance USD-M", symbol: "BTCUSDT" },
];

const INTENTS: Array<{ value: Intent; label: string; tone: "buy" | "sell" }> = [
  { value: "open_long", label: "开多", tone: "buy" },
  { value: "close_long", label: "平多", tone: "sell" },
  { value: "open_short", label: "开空", tone: "sell" },
  { value: "close_short", label: "平空", tone: "buy" },
];

function formatNumber(value: number | undefined, digits = 4) {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(4)}%`;
}

function initialPositionSide(intent: Intent): PositionSide {
  if (intent.endsWith("long")) return "long";
  if (intent.endsWith("short")) return "short";
  return "net";
}

function isCloseIntent(intent: Intent) {
  return intent === "close_long" || intent === "close_short";
}

export default function App() {
  const [exchange, setExchange] = useState<ExchangeName>("okx_swap");
  const [symbol, setSymbol] = useState("BTC-USDT-SWAP");
  const [intent, setIntent] = useState<Intent>("open_long");
  const [quantity, setQuantity] = useState("1");
  const [price, setPrice] = useState("100000");
  const [leverage, setLeverage] = useState("3");
  const [orderType, setOrderType] = useState<ContractOrderPayload["order_type"]>("post_only");
  const [marginMode, setMarginMode] = useState<MarginMode>("cross");
  const [positionSide, setPositionSide] = useState<PositionSide>("long");
  const [liquidity, setLiquidity] = useState<Liquidity>("maker");

  const [apiOnline, setApiOnline] = useState(false);
  const [healthEnv, setHealthEnv] = useState("--");
  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [feeRate, setFeeRate] = useState<FeeRate | null>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("等待连接后端");
  const [error, setError] = useState("");

  const numericQuantity = Number(quantity);
  const numericPrice = Number(price);
  const liveEnabled = engine?.risk.trading_enabled ?? false;
  const orderBlocked = !liveEnabled || !apiOnline;
  const notional = numericQuantity * numericPrice;

  const selectedExchangeLabel = useMemo(
    () => EXCHANGE_OPTIONS.find((item) => item.value === exchange)?.label ?? exchange,
    [exchange],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const [health, exchanges, status] = await Promise.all([
        api.health(),
        api.exchanges(),
        api.engineStatus(),
      ]);
      setApiOnline(health.status === "ok");
      setHealthEnv(health.env);
      setSupportedExchanges(exchanges.exchanges);
      setEngine(status);
      setError("");
      setMessage("后端连接正常");
    } catch (err) {
      setApiOnline(false);
      setError(err instanceof Error ? err.message : "后端连接失败");
      setMessage("后端离线");
    }
  }, []);

  const refreshFeeAndCost = useCallback(async () => {
    if (!apiOnline || numericQuantity <= 0 || numericPrice <= 0) return;
    try {
      const [fee, cost] = await Promise.all([
        api.feeRate(exchange, symbol),
        api.costEstimate(exchange, symbol, numericQuantity, numericPrice, liquidity),
      ]);
      setFeeRate(fee);
      setEstimate(cost);
      setError("");
    } catch (err) {
      setFeeRate(null);
      setEstimate(null);
      setError(err instanceof Error ? err.message : "手续费/成本估算失败");
    }
  }, [apiOnline, exchange, liquidity, numericPrice, numericQuantity, symbol]);

  useEffect(() => {
    refreshStatus();
    const id = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    refreshFeeAndCost();
  }, [refreshFeeAndCost]);

  function handleExchangeChange(value: ExchangeName) {
    const item = EXCHANGE_OPTIONS.find((option) => option.value === value);
    setExchange(value);
    if (item) setSymbol(item.symbol);
  }

  function handleIntentChange(nextIntent: Intent) {
    setIntent(nextIntent);
    setPositionSide(initialPositionSide(nextIntent));
    if (isCloseIntent(nextIntent)) setLiquidity("maker");
  }

  async function submitOrder() {
    setBusy(true);
    setError("");
    try {
      if (orderBlocked) {
        throw new Error("当前未允许真实交易，后端会拒绝下单。");
      }
      if (orderType === "market") {
        const ok = window.confirm("Market 单会直接吃单成交，确认继续？");
        if (!ok) return;
      }
      const payload: ContractOrderPayload = {
        exchange,
        symbol,
        intent,
        quantity: numericQuantity,
        order_type: orderType,
        margin_mode: marginMode,
        position_side: positionSide,
        reduce_only: isCloseIntent(intent),
      };
      if (orderType !== "market") payload.price = numericPrice;
      const lev = Number(leverage);
      if (lev > 0) payload.leverage = lev;

      const result = await api.placeContractOrder(payload);
      setMessage(`订单已提交：${String(result.order_id ?? "pending")}`);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "下单失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Personal Contract Desk</p>
          <h1>Web3 Trading Console</h1>
        </div>
        <div className="status-cluster">
          <span className={`status-pill ${apiOnline ? "ok" : "bad"}`}>
            {apiOnline ? <Wifi size={16} /> : <WifiOff size={16} />}
            API {apiOnline ? "ONLINE" : "OFFLINE"}
          </span>
          <span className={`status-pill ${liveEnabled ? "danger" : "safe"}`}>
            <Power size={16} />
            LIVE {liveEnabled ? "ON" : "OFF"}
          </span>
          <span className="status-pill neutral">
            <CircleDot size={16} />
            {healthEnv}
          </span>
        </div>
      </section>

      <section className="workspace">
        <aside className="panel order-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Execution</p>
              <h2>快速合约下单</h2>
            </div>
            <button className="icon-button" onClick={refreshStatus} title="刷新状态">
              <RefreshCw size={18} />
            </button>
          </div>

          <label className="field">
            <span>交易所</span>
            <select value={exchange} onChange={(event) => handleExchangeChange(event.target.value as ExchangeName)}>
              {EXCHANGE_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>合约</span>
            <input value={symbol} onChange={(event) => setSymbol(event.target.value)} />
          </label>

          <div className="segmented intent-grid">
            {INTENTS.map((item) => (
              <button
                key={item.value}
                className={`${intent === item.value ? "active" : ""} ${item.tone}`}
                onClick={() => handleIntentChange(item.value)}
                type="button"
              >
                {item.tone === "buy" ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                {item.label}
              </button>
            ))}
          </div>

          <div className="two-col">
            <label className="field">
              <span>数量</span>
              <input value={quantity} onChange={(event) => setQuantity(event.target.value)} inputMode="decimal" />
            </label>
            <label className="field">
              <span>价格</span>
              <input value={price} onChange={(event) => setPrice(event.target.value)} inputMode="decimal" />
            </label>
          </div>

          <div className="two-col">
            <label className="field">
              <span>杠杆</span>
              <input value={leverage} onChange={(event) => setLeverage(event.target.value)} inputMode="numeric" />
            </label>
            <label className="field">
              <span>保证金</span>
              <select value={marginMode} onChange={(event) => setMarginMode(event.target.value as MarginMode)}>
                <option value="cross">全仓</option>
                <option value="isolated">逐仓</option>
              </select>
            </label>
          </div>

          <div className="two-col">
            <label className="field">
              <span>订单类型</span>
              <select
                value={orderType}
                onChange={(event) => {
                  const value = event.target.value as ContractOrderPayload["order_type"];
                  setOrderType(value);
                  setLiquidity(value === "market" || value === "ioc" || value === "fok" ? "taker" : "maker");
                }}
              >
                <option value="post_only">Post Only</option>
                <option value="limit">Limit</option>
                <option value="market">Market</option>
                <option value="ioc">IOC</option>
                <option value="fok">FOK</option>
              </select>
            </label>
            <label className="field">
              <span>仓位方向</span>
              <select value={positionSide} onChange={(event) => setPositionSide(event.target.value as PositionSide)}>
                <option value="long">Long</option>
                <option value="short">Short</option>
                <option value="net">Net</option>
              </select>
            </label>
          </div>

          <button className="primary-action" onClick={submitOrder} disabled={busy || orderBlocked}>
            <Send size={18} />
            {busy ? "提交中" : orderBlocked ? "Live Off" : "提交订单"}
          </button>

          <div className={`notice ${error ? "error" : "info"}`}>
            {error ? <ShieldAlert size={18} /> : <Activity size={18} />}
            {error || message}
          </div>
        </aside>

        <section className="panel market-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{selectedExchangeLabel}</p>
              <h2>手续费与成本</h2>
            </div>
            <span className="symbol-badge">{symbol}</span>
          </div>

          <div className="metric-grid">
            <Metric label="名义价值" value={`$${formatNumber(notional, 2)}`} />
            <Metric label="Maker" value={formatPercent(feeRate?.maker)} />
            <Metric label="Taker" value={formatPercent(feeRate?.taker)} />
            <Metric label="预估手续费" value={`$${formatNumber(estimate?.estimated_fee, 4)}`} accent />
          </div>

          <div className="liquidity-toggle">
            <button className={liquidity === "maker" ? "active" : ""} onClick={() => setLiquidity("maker")}>
              Maker 优先
            </button>
            <button className={liquidity === "taker" ? "active" : ""} onClick={() => setLiquidity("taker")}>
              Taker 逃生
            </button>
          </div>

          <div className="cost-card">
            <BadgeDollarSign size={24} />
            <div>
              <strong>执行提示</strong>
              <p>
                默认用 Post Only 争取 maker 费率；遇到止损、极端行情或需要快速离场时，用 taker，不要为了省手续费扩大风险。
              </p>
            </div>
          </div>

          <div className="mini-table">
            <div>
              <span>Exchange</span>
              <strong>{estimate?.exchange ?? exchange}</strong>
            </div>
            <div>
              <span>Liquidity</span>
              <strong>{estimate?.liquidity ?? liquidity}</strong>
            </div>
            <div>
              <span>Fee Rate</span>
              <strong>{formatPercent(estimate?.fee_rate)}</strong>
            </div>
          </div>
        </section>

        <aside className="panel risk-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Account Guard</p>
              <h2>状态与风险</h2>
            </div>
            <Gauge size={22} />
          </div>

          <div className="risk-stack">
            <Metric label="每分钟订单" value={`${engine?.risk.orders_last_minute ?? 0}/${engine?.risk.max_orders_per_minute ?? 0}`} />
            <Metric label="当日 PnL" value={`$${formatNumber(engine?.risk.daily_pnl ?? 0, 2)}`} />
            <Metric label="当前回撤" value={`${formatNumber((engine?.risk.current_drawdown ?? 0) * 100, 2)}%`} />
            <Metric label="活跃仓位" value={String(engine?.positions.active_positions ?? 0)} />
          </div>

          <div className="positions">
            <div className="section-title">
              <span>Positions</span>
              <small>{engine?.timestamp ? new Date(engine.timestamp).toLocaleTimeString() : "--"}</small>
            </div>
            {engine?.positions.positions.length ? (
              engine.positions.positions.map((position) => (
                <div className="position-row" key={`${position.exchange}-${position.symbol}`}>
                  <div>
                    <strong>{position.symbol}</strong>
                    <span>{position.exchange}</span>
                  </div>
                  <div>
                    <strong>{formatNumber(position.quantity, 6)}</strong>
                    <span>{formatNumber(position.pnl_pct, 2)}%</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">
                <AlertTriangle size={18} />
                暂无本地持仓记录
              </div>
            )}
          </div>

          <div className="supported">
            <span>后端支持</span>
            <div>
              {supportedExchanges.map((item) => (
                <code key={item}>{item}</code>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`metric ${accent ? "accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
