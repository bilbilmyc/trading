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
  AppConfig,
  AuditEvent,
  ContractMarket,
  ContractOrderPayload,
  ContractOrderPreview,
  CostEstimate,
  EngineStatus,
  ExchangeName,
  FeeRate,
  Intent,
  KillSwitchStatus,
  Liquidity,
  MarginMode,
  OpenOrder,
  PaperSummary,
  PositionSide,
  RecentTrade,
  SignalRunnerStatus,
  StrategyInfo,
  StrategySignal,
  Ticker,
} from "./api";

const EXCHANGE_OPTIONS: Array<{ value: ExchangeName; label: string }> = [
  { value: "binance_usdm", label: "Binance U 本位合约" },
  { value: "bitget_usdt_futures", label: "Bitget U 本位合约" },
  { value: "okx_swap", label: "OKX 永续合约" },
];

const INTENTS: Array<{ value: Intent; label: string; tone: "buy" | "sell" }> = [
  { value: "open_long", label: "买入开多", tone: "buy" },
  { value: "close_long", label: "卖出平多", tone: "sell" },
  { value: "open_short", label: "卖出开空", tone: "sell" },
  { value: "close_short", label: "买入平空", tone: "buy" },
];

const EVENT_LABELS: Record<string, string> = {
  live_trading_blocked: "实盘守卫拦截",
  kill_switch_enabled: "Kill Switch 开启",
  kill_switch_disabled: "Kill Switch 解除",
  kill_switch_blocked: "Kill Switch 拦截",
  order_rejected_by_risk: "风控拒单",
  live_order_submitted: "策略实盘下单",
  live_order_failed: "策略下单失败",
  spot_order_submitted: "现货订单提交",
  contract_order_submitted: "合约订单提交",
  order_cancel_requested: "撤单请求",
  cancel_all_requested: "批量撤单请求",
  leverage_changed: "杠杆调整",
};

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

function formatEventType(eventType: string) {
  return EVENT_LABELS[eventType] ?? eventType.replaceAll("_", " ");
}

function initialPositionSide(intent: Intent): PositionSide {
  if (intent.endsWith("long")) return "long";
  if (intent.endsWith("short")) return "short";
  return "net";
}

function isCloseIntent(intent: Intent) {
  return intent === "close_long" || intent === "close_short";
}

function formatQuantitySeed(market: ContractMarket | undefined) {
  if (!market?.min_quantity || market.min_quantity <= 0) return "1";
  return String(market.min_quantity);
}

export default function App() {
  const [exchange, setExchange] = useState<ExchangeName>("binance_usdm");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [contractSearch, setContractSearch] = useState("");
  const [contracts, setContracts] = useState<ContractMarket[]>([]);
  const [contractsLoading, setContractsLoading] = useState(false);
  const [contractsTotal, setContractsTotal] = useState(0);
  const [intent, setIntent] = useState<Intent>("open_long");
  const [quantity, setQuantity] = useState("0.001");
  const [price, setPrice] = useState("100000");
  const [priceSyncedSymbol, setPriceSyncedSymbol] = useState("");
  const [leverage, setLeverage] = useState("3");
  const [orderType, setOrderType] = useState<ContractOrderPayload["order_type"]>("post_only");
  const [marginMode, setMarginMode] = useState<MarginMode>("cross");
  const [positionSide, setPositionSide] = useState<PositionSide>("long");
  const [liquidity, setLiquidity] = useState<Liquidity>("maker");

  const [apiOnline, setApiOnline] = useState(false);
  const [healthEnv, setHealthEnv] = useState("--");
  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [enabledExchanges, setEnabledExchanges] = useState<string[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [runner, setRunner] = useState<SignalRunnerStatus | null>(null);
  const [paper, setPaper] = useState<PaperSummary | null>(null);
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [trades, setTrades] = useState<RecentTrade[]>([]);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [feeRate, setFeeRate] = useState<FeeRate | null>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [orderPreview, setOrderPreview] = useState<ContractOrderPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [killBusy, setKillBusy] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [strategyBusy, setStrategyBusy] = useState("");
  const [runnerBusy, setRunnerBusy] = useState("");
  const [strategyName, setStrategyName] = useState("");
  const [shortWindow, setShortWindow] = useState("5");
  const [longWindow, setLongWindow] = useState("20");
  const [strategyInterval, setStrategyInterval] = useState("1m");
  const [strategyMode, setStrategyMode] = useState<"signal" | "paper">("paper");
  const [message, setMessage] = useState("等待连接后端");
  const [error, setError] = useState("");
  const [costError, setCostError] = useState("");
  const [marketError, setMarketError] = useState("");

  const numericQuantity = Number(quantity);
  const numericPrice = Number(price);
  const liveEnabled = config?.live_trading_enabled ?? false;
  const killSwitchEnabled = killSwitch?.enabled ?? !(engine?.risk.trading_enabled ?? true);
  const orderBlockedReason = !apiOnline ? "后端离线" : killSwitchEnabled ? "Kill Switch 已开启" : !liveEnabled ? "实盘未开启" : "";
  const orderBlocked = Boolean(orderBlockedReason);
  const notional = numericQuantity * numericPrice;

  const selectedExchangeLabel = useMemo(
    () => EXCHANGE_OPTIONS.find((item) => item.value === exchange)?.label ?? exchange,
    [exchange],
  );
  const selectedContract = useMemo(
    () => contracts.find((item) => item.symbol === symbol),
    [contracts, symbol],
  );
  const selectedContractLabel = selectedContract
    ? `${selectedContract.base_asset} / ${selectedContract.quote_asset}`
    : symbol || "请选择合约";

  const refreshStatus = useCallback(async () => {
    try {
      const [
        health,
        exchanges,
        status,
        runtimeConfig,
        strategyResult,
        signalResult,
        eventResult,
        killSwitchResult,
        runnerStatus,
        paperStatus,
      ] = await Promise.all([
        api.health(),
        api.exchanges(),
        api.engineStatus(),
        api.config(),
        api.strategies(),
        api.recentSignals(10),
        api.recentEvents(12),
        api.killSwitchStatus(),
        api.runnerStatus(),
        api.paper(),
      ]);
      setApiOnline(health.status === "ok");
      setHealthEnv(health.env);
      setSupportedExchanges(exchanges.exchanges);
      setEnabledExchanges(exchanges.enabled);
      setConfig(runtimeConfig);
      setEngine(status);
      setStrategies(strategyResult.strategies);
      setSignals(signalResult.signals);
      setEvents(eventResult.events);
      setKillSwitch(killSwitchResult);
      setRunner(runnerStatus);
      setPaper(paperStatus);
      setError("");
      setMessage("后端连接正常");
    } catch (err) {
      setApiOnline(false);
      setError(err instanceof Error ? err.message : "后端连接失败");
      setMessage("后端离线");
    }
  }, []);

  const refreshMarket = useCallback(async () => {
    if (!apiOnline || !symbol) return;
    const [tickerResult, tradesResult, ordersResult] = await Promise.allSettled([
      api.ticker(exchange, symbol),
      api.recentTrades(exchange, symbol),
      api.openOrders(exchange, symbol),
    ]);

    if (tickerResult.status === "fulfilled") setTicker(tickerResult.value);
    else setTicker(null);

    if (
      tickerResult.status === "fulfilled" &&
      tickerResult.value.last_price > 0 &&
      priceSyncedSymbol !== symbol
    ) {
      setPrice(String(tickerResult.value.last_price));
      setPriceSyncedSymbol(symbol);
    }

    if (tradesResult.status === "fulfilled") setTrades(tradesResult.value);
    else setTrades([]);

    if (ordersResult.status === "fulfilled") setOpenOrders(ordersResult.value);
    else setOpenOrders([]);

    const failed = [tickerResult, tradesResult].find((item) => item.status === "rejected");
    setMarketError(failed?.status === "rejected" ? failed.reason?.message ?? "行情刷新失败" : "");
  }, [apiOnline, exchange, priceSyncedSymbol, symbol]);

  const refreshContracts = useCallback(async () => {
    if (!apiOnline) return;
    setContractsLoading(true);
    try {
      const result = await api.contracts(exchange, contractSearch, 200);
      setContracts(result.contracts);
      setContractsTotal(result.total);
      setMarketError("");
      if (!symbol || !result.contracts.some((item) => item.symbol === symbol)) {
        const next = result.contracts[0];
        if (next) {
          setSymbol(next.symbol);
          setQuantity(formatQuantitySeed(next));
        }
      }
    } catch (err) {
      setContracts([]);
      setContractsTotal(0);
      setMarketError(err instanceof Error ? err.message : "合约列表获取失败");
    } finally {
      setContractsLoading(false);
    }
  }, [apiOnline, contractSearch, exchange, symbol]);

  const refreshFeeAndCost = useCallback(async () => {
    if (!apiOnline || !symbol || numericQuantity <= 0 || numericPrice <= 0) return;
    try {
      const [fee, cost] = await Promise.all([
        api.feeRate(exchange, symbol),
        api.costEstimate(exchange, symbol, numericQuantity, numericPrice, liquidity),
      ]);
      setFeeRate(fee);
      setEstimate(cost);
      setCostError("");
    } catch (err) {
      setFeeRate(null);
      setEstimate(null);
      setCostError(err instanceof Error ? err.message : "手续费/成本估算失败");
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

  useEffect(() => {
    refreshMarket();
  }, [refreshMarket]);

  useEffect(() => {
    refreshContracts();
  }, [refreshContracts]);

  useEffect(() => {
    setOrderPreview(null);
  }, [exchange, symbol, intent, quantity, price, leverage, orderType, marginMode, positionSide]);

  function buildContractOrderPayload(clientOrderId?: string): ContractOrderPayload {
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
    if (clientOrderId) payload.client_order_id = clientOrderId;
    return payload;
  }

  function handleExchangeChange(value: ExchangeName) {
    setExchange(value);
    setSymbol("");
    setTicker(null);
    setTrades([]);
    setOpenOrders([]);
    setPriceSyncedSymbol("");
  }

  async function handleContractSelect(contract: ContractMarket) {
    setSymbol(contract.symbol);
    setQuantity(formatQuantitySeed(contract));
    setError("");
    try {
      const latest = await api.ticker(exchange, contract.symbol);
      setTicker(latest);
      if (latest.last_price > 0) {
        setPrice(String(latest.last_price));
        setPriceSyncedSymbol(contract.symbol);
      }
    } catch (err) {
      setMarketError(err instanceof Error ? err.message : "最新价格获取失败");
    }
  }

  function handleIntentChange(nextIntent: Intent) {
    setIntent(nextIntent);
    setPositionSide(initialPositionSide(nextIntent));
    if (isCloseIntent(nextIntent)) setLiquidity("maker");
  }

  async function previewCurrentOrder(payload = buildContractOrderPayload()) {
    if (!apiOnline || !symbol) throw new Error("后端离线或合约为空，无法生成预览。");
    setPreviewBusy(true);
    setError("");
    try {
      const preview = await api.previewContractOrder(payload);
      setOrderPreview(preview);
      setMessage(`已生成下单预览：${preview.client_order_id}`);
      await refreshStatus();
      return preview;
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成下单预览失败");
      throw err;
    } finally {
      setPreviewBusy(false);
    }
  }

  async function submitOrder() {
    setBusy(true);
    setError("");
    try {
      if (orderBlocked) {
        throw new Error(`${orderBlockedReason}，后端会拒绝真实下单。`);
      }
      const payload = buildContractOrderPayload(orderPreview?.client_order_id);
      const preview = await previewCurrentOrder(payload);
      if (orderType === "market") {
        const ok = window.confirm("Market 单会直接吃单成交，确认继续？");
        if (!ok) return;
      }
      const confirmed = window.confirm(
        `确认提交订单？\n订单号：${preview.client_order_id}\n名义价值：$${formatNumber(preview.notional, 2)}\n预估手续费：$${formatNumber(preview.estimated_fee ?? undefined, 4)}`,
      );
      if (!confirmed) return;

      const result = await api.placeContractOrder({
        ...payload,
        client_order_id: preview.client_order_id,
      });
      setMessage(`订单已提交：${String(result.order_id ?? "pending")}`);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "下单失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleKillSwitch() {
    const nextEnabled = !killSwitchEnabled;
    if (nextEnabled) {
      const confirmed = window.confirm("确认开启全局 Kill Switch？开启后手动下单、撤单、调杠杆和策略实盘下单都会被拦截。");
      if (!confirmed) return;
    }

    setKillBusy(true);
    setError("");
    try {
      const next = await api.setKillSwitch(
        nextEnabled,
        nextEnabled ? "manual_frontend_enable" : "manual_frontend_disable",
      );
      setKillSwitch(next);
      await refreshStatus();
      setMessage(nextEnabled ? "全局 Kill Switch 已开启" : "全局 Kill Switch 已解除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换 Kill Switch 失败");
    } finally {
      setKillBusy(false);
    }
  }

  async function evaluateCurrentStrategy() {
    if (!symbol) return;
    setEvaluating(true);
    setError("");
    try {
      const result = await api.evaluateSignals(exchange, symbol);
      setSignals(result.recent_signals);
      setMessage(`已处理 ${result.candles_processed} 根 K 线，生成 ${result.signals.length} 个信号`);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "策略评估失败");
    } finally {
      setEvaluating(false);
    }
  }

  async function createSmaStrategy() {
    if (!symbol) return;
    setStrategyBusy("create");
    setError("");
    try {
      await api.createSmaStrategy({
        name: strategyName || undefined,
        exchange,
        symbol,
        interval: strategyInterval,
        short_window: Number(shortWindow),
        long_window: Number(longWindow),
        enabled: true,
        mode: strategyMode,
      });
      setStrategyName("");
      await refreshStatus();
      setMessage("SMA 策略已创建并启用");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建策略失败");
    } finally {
      setStrategyBusy("");
    }
  }

  async function toggleStrategy(strategy: StrategyInfo) {
    setStrategyBusy(strategy.name);
    setError("");
    try {
      if (strategy.running) {
        await api.stopStrategy(strategy.name);
      } else {
        await api.startStrategy(strategy.name);
      }
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新策略状态失败");
    } finally {
      setStrategyBusy("");
    }
  }

  async function toggleStrategyMode(strategy: StrategyInfo) {
    setStrategyBusy(strategy.name);
    setError("");
    try {
      await api.setStrategyMode(strategy.name, strategy.mode === "paper" ? "signal" : "paper");
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换策略模式失败");
    } finally {
      setStrategyBusy("");
    }
  }

  async function resetPaperAccount() {
    setRunnerBusy("paper-reset");
    setError("");
    try {
      const next = await api.resetPaper();
      setPaper(next);
      setMessage("模拟盘已重置");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置模拟盘失败");
    } finally {
      setRunnerBusy("");
    }
  }

  async function startRunner() {
    setRunnerBusy("start");
    setError("");
    try {
      const next = await api.startRunner(60, 80);
      setRunner(next);
      await refreshStatus();
      setMessage("策略运行器已启动，只记录信号，不自动下单");
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动运行器失败");
    } finally {
      setRunnerBusy("");
    }
  }

  async function stopRunner() {
    setRunnerBusy("stop");
    setError("");
    try {
      const next = await api.stopRunner();
      setRunner(next);
      await refreshStatus();
      setMessage("策略运行器已停止");
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止运行器失败");
    } finally {
      setRunnerBusy("");
    }
  }

  async function runOneSignalCycle() {
    setRunnerBusy("once");
    setError("");
    try {
      const result = await api.runSignalCycle(60, 80);
      setRunner(result.status);
      setSignals(result.signals.length ? result.signals : signals);
      setMessage(`运行器处理 ${result.processed_strategies} 个策略，生成 ${result.signals.length} 个信号`);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行策略周期失败");
    } finally {
      setRunnerBusy("");
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">合约交易控制台</p>
          <h1>合约下单与风险面板</h1>
        </div>
        <div className="status-cluster">
          <span className={`status-pill ${apiOnline ? "ok" : "bad"}`}>
            {apiOnline ? <Wifi size={16} /> : <WifiOff size={16} />}
            后端 {apiOnline ? "在线" : "离线"}
          </span>
          <span className={`status-pill ${liveEnabled ? "danger" : "safe"}`}>
            <Power size={16} />
            实盘 {liveEnabled ? "开启" : "关闭"}
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
              <p className="eyebrow">下单</p>
              <h2>选择交易方向</h2>
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

          <div className="field">
            <span>搜索合约</span>
            <input
              placeholder="输入 BTC、ETH、SOL、DOGE..."
              value={contractSearch}
              onChange={(event) => setContractSearch(event.target.value)}
            />
          </div>

          <div className="field">
            <span>可交易 USDT 永续合约 {contractsLoading ? "加载中" : `(${contractsTotal})`}</span>
            <div className="market-picker">
              {contracts.slice(0, 12).map((item) => (
                <button
                  className={symbol === item.symbol ? "active" : ""}
                  key={item.symbol}
                  onClick={() => handleContractSelect(item)}
                  type="button"
                >
                  <strong>{item.base_asset}</strong>
                  <small>{item.symbol}</small>
                </button>
              ))}
              {!contracts.length && <div className="empty-state">没有匹配的合约</div>}
            </div>
          </div>

          <label className="field">
            <span>合约代码</span>
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
              <span>下单数量</span>
              <input value={quantity} onChange={(event) => setQuantity(event.target.value)} inputMode="decimal" />
            </label>
            <label className="field">
              <span>委托价格</span>
              <input value={price} onChange={(event) => setPrice(event.target.value)} inputMode="decimal" />
            </label>
          </div>

          <div className="two-col">
            <label className="field">
              <span>杠杆倍数</span>
              <input value={leverage} onChange={(event) => setLeverage(event.target.value)} inputMode="numeric" />
            </label>
            <label className="field">
              <span>保证金模式</span>
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
                <option value="post_only">只挂单</option>
                <option value="limit">限价单</option>
                <option value="market">市价单</option>
                <option value="ioc">IOC</option>
                <option value="fok">FOK</option>
              </select>
            </label>
            <label className="field">
              <span>仓位方向</span>
              <select value={positionSide} onChange={(event) => setPositionSide(event.target.value as PositionSide)}>
                <option value="long">多仓</option>
                <option value="short">空仓</option>
                <option value="net">单向持仓</option>
              </select>
            </label>
          </div>

          <button
            className="secondary-action full-width"
            onClick={() => previewCurrentOrder().catch(() => undefined)}
            disabled={previewBusy || !apiOnline || !symbol || numericQuantity <= 0}
            type="button"
          >
            <RefreshCw size={16} />
            {previewBusy ? "预览中" : "生成下单预览"}
          </button>

          {orderPreview && (
            <div className="preview-card">
              <div className="section-title">
                <span>下单预览</span>
                <small>{orderPreview.client_order_id}</small>
              </div>
              <div className="preview-grid">
                <Metric label="名义价值" value={`$${formatNumber(orderPreview.notional, 2)}`} />
                <Metric label="初始保证金" value={`$${formatNumber(orderPreview.initial_margin, 2)}`} />
                <Metric label="预估手续费" value={`$${formatNumber(orderPreview.estimated_fee ?? undefined, 4)}`} />
                <Metric label="Reduce Only" value={orderPreview.reduce_only ? "是" : "否"} />
              </div>
              <p>{orderPreview.liquidation_risk_note}</p>
            </div>
          )}

          <button className="primary-action" onClick={submitOrder} disabled={busy || orderBlocked}>
            <Send size={18} />
            {busy ? "提交中" : orderBlocked ? orderBlockedReason : "预览后提交"}
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
              <h2>{selectedContractLabel} 行情与成本</h2>
            </div>
            <span className="symbol-badge">{symbol}</span>
          </div>

          <div className="strategy-summary">
            <div>
              <span>策略</span>
              <strong>{strategies.length}</strong>
            </div>
            <div>
              <span>最近信号</span>
              <strong>{signals.length}</strong>
            </div>
            <div>
              <span>运行器</span>
              <strong>{runner?.running ? "运行" : "停止"}</strong>
            </div>
            <button className="secondary-action" onClick={evaluateCurrentStrategy} disabled={evaluating || !symbol}>
              <RefreshCw size={16} />
              {evaluating ? "评估中" : "评估当前合约"}
            </button>
          </div>

          <div className="runner-controls">
            <button className="secondary-action" onClick={startRunner} disabled={runner?.running || !!runnerBusy}>
              启动运行器
            </button>
            <button className="secondary-action" onClick={stopRunner} disabled={!runner?.running || !!runnerBusy}>
              停止运行器
            </button>
            <button className="secondary-action" onClick={runOneSignalCycle} disabled={!!runnerBusy}>
              {runnerBusy === "once" ? "运行中" : "手动跑一轮"}
            </button>
            <span>
              周期 {runner?.cycles ?? 0} · 信号 {runner?.signals_generated ?? 0}
              {runner?.last_error ? ` · 错误 ${runner.last_error}` : ""}
            </span>
          </div>

          <div className="signals-list">
            <div className="section-title">
              <span>策略信号</span>
              <small>只观察，不自动下单</small>
            </div>
            {signals.length ? (
              signals.slice(0, 4).map((signal) => (
                <div className="signal-row" key={`${signal.strategy}-${signal.symbol}-${signal.timestamp}`}>
                  <div>
                    <strong>{signal.strategy}</strong>
                    <span>{signal.symbol}</span>
                  </div>
                  <div>
                    <strong className={signal.action === "buy" ? "buy-text" : "sell-text"}>
                      {signal.action === "buy" ? "买入" : signal.action === "sell" ? "卖出" : "观望"}
                    </strong>
                    <span>{new Date(signal.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无策略信号，点击评估当前合约</div>
            )}
          </div>

          <div className="metric-grid">
            <Metric label="最新价格" value={`$${formatNumber(ticker?.last_price, 2)}`} />
            <Metric label="24h 涨跌" value={`${formatNumber(ticker?.price_change_pct_24h, 2)}%`} />
            <Metric label="名义价值" value={`$${formatNumber(notional, 2)}`} />
            <Metric label="24h 成交额" value={`$${formatNumber(ticker?.quote_volume_24h, 0)}`} />
            <Metric label="Maker" value={formatPercent(feeRate?.maker)} />
            <Metric label="Taker" value={formatPercent(feeRate?.taker)} />
            <Metric label="预估手续费" value={`$${formatNumber(estimate?.estimated_fee, 4)}`} accent />
          </div>

          <div className="liquidity-toggle">
            <button className={liquidity === "maker" ? "active" : ""} onClick={() => setLiquidity("maker")}>
              挂单费率
            </button>
            <button className={liquidity === "taker" ? "active" : ""} onClick={() => setLiquidity("taker")}>
              吃单费率
            </button>
          </div>

          <div className="cost-card">
            <BadgeDollarSign size={24} />
            <div>
              <strong>执行提示</strong>
              <p>
                实盘关闭时不会真实下单；开启实盘后，市价单和吃单会更快成交，也更容易产生滑点。
              </p>
            </div>
          </div>

          <div className="mini-table">
            <div>
              <span>Exchange</span>
              <strong>{estimate?.exchange ?? exchange}</strong>
            </div>
            <div>
              <span>费率类型</span>
              <strong>{(estimate?.liquidity ?? liquidity) === "maker" ? "挂单" : "吃单"}</strong>
            </div>
            <div>
              <span>手续费率</span>
              <strong>{formatPercent(estimate?.fee_rate)}</strong>
            </div>
          </div>

          {(marketError || costError) && (
            <div className="notice error compact">
              <ShieldAlert size={18} />
              {marketError || costError}
            </div>
          )}

          <div className="market-lists">
            <div>
              <div className="section-title">
                <span>最近成交</span>
                <small>{trades.length}</small>
              </div>
              {trades.length ? (
                trades.map((trade) => (
                  <div className="trade-row" key={trade.trade_id}>
                    <span className={trade.side === "buy" ? "buy-text" : "sell-text"}>
                      {trade.side === "buy" ? "买" : "卖"}
                    </span>
                    <strong>{formatNumber(trade.price, 2)}</strong>
                    <small>{formatNumber(trade.quantity, 6)}</small>
                  </div>
                ))
              ) : (
                <div className="empty-state">暂无成交数据</div>
              )}
            </div>

            <div>
              <div className="section-title">
                <span>当前挂单</span>
                <small>{openOrders.length}</small>
              </div>
              {openOrders.length ? (
                openOrders.slice(0, 8).map((order, index) => (
                  <div className="trade-row" key={String(order.order_id ?? order.orderId ?? index)}>
                    <span>{order.side ?? "--"}</span>
                    <strong>{String(order.price ?? "--")}</strong>
                    <small>{String(order.status ?? order.quantity ?? order.origQty ?? "--")}</small>
                  </div>
                ))
              ) : (
                <div className="empty-state">暂无挂单</div>
              )}
            </div>
          </div>
        </section>

        <aside className="panel risk-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Account Guard</p>
              <h2>账户状态</h2>
            </div>
            <Gauge size={22} />
          </div>

          <div className={`kill-switch ${killSwitchEnabled ? "active" : ""}`}>
            <div>
              <strong>全局 Kill Switch</strong>
              <span>{killSwitchEnabled ? "已熔断全部真实交易" : "真实交易风控闸门正常"}</span>
            </div>
            <button
              className={`state-button ${killSwitchEnabled ? "running" : "danger"}`}
              onClick={toggleKillSwitch}
              disabled={killBusy || !apiOnline}
              title={killSwitchEnabled ? "解除全局 Kill Switch" : "开启全局 Kill Switch"}
              type="button"
            >
              <Power size={15} />
              {killBusy ? "处理中" : killSwitchEnabled ? "解除" : "熔断"}
            </button>
          </div>

          <div className="risk-stack">
            <Metric label="每分钟订单" value={`${engine?.risk.orders_last_minute ?? 0}/${engine?.risk.max_orders_per_minute ?? 0}`} />
            <Metric label="当日 PnL" value={`$${formatNumber(engine?.risk.daily_pnl ?? 0, 2)}`} />
            <Metric label="当前回撤" value={`${formatNumber((engine?.risk.current_drawdown ?? 0) * 100, 2)}%`} />
            <Metric label="活跃仓位" value={String(engine?.positions.active_positions ?? 0)} />
          </div>

          <div className="audit-panel">
            <div className="section-title">
              <span>审计事件</span>
              <small>{events.length}</small>
            </div>
            {events.length ? (
              events
                .slice()
                .reverse()
                .map((event) => (
                  <div className={`event-row ${event.level}`} key={event.id}>
                    <div className="event-marker" />
                    <div>
                      <strong>{formatEventType(event.event_type)}</strong>
                      <span>
                        {event.exchange ?? "--"} · {event.symbol ?? "--"} ·{" "}
                        {new Date(event.timestamp).toLocaleTimeString()}
                      </span>
                      <p>{event.message}</p>
                    </div>
                  </div>
                ))
            ) : (
              <div className="empty-state">暂无订单或风控审计事件</div>
            )}
          </div>

          <div className="strategies">
            <div className="section-title">
              <span>已加载策略</span>
              <small>{strategies.length}</small>
            </div>
            <div className="strategy-form">
              <input
                placeholder="策略名称，可空"
                value={strategyName}
                onChange={(event) => setStrategyName(event.target.value)}
              />
              <input value={shortWindow} onChange={(event) => setShortWindow(event.target.value)} inputMode="numeric" />
              <input value={longWindow} onChange={(event) => setLongWindow(event.target.value)} inputMode="numeric" />
              <select value={strategyInterval} onChange={(event) => setStrategyInterval(event.target.value)}>
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
              </select>
              <select value={strategyMode} onChange={(event) => setStrategyMode(event.target.value as "signal" | "paper")}>
                <option value="paper">模拟盘</option>
                <option value="signal">只信号</option>
              </select>
              <button className="secondary-action" onClick={createSmaStrategy} disabled={strategyBusy === "create" || !symbol}>
                {strategyBusy === "create" ? "创建中" : "创建 SMA"}
              </button>
            </div>
            {strategies.map((strategy) => (
              <div className="strategy-row" key={strategy.name}>
                <div>
                  <strong>{strategy.name}</strong>
                  <span>
                    {strategy.class_name} · {strategy.exchange ?? "--"} · {strategy.symbol ?? "--"} ·{" "}
                    {strategy.interval ?? "1m"} · {strategy.mode === "paper" ? "模拟盘" : "只信号"}
                  </span>
                </div>
                <div className="strategy-actions">
                  <button
                    className={`state-button ${strategy.mode === "paper" ? "paper" : ""}`}
                    onClick={() => toggleStrategyMode(strategy)}
                    disabled={strategyBusy === strategy.name}
                  >
                    {strategy.mode === "paper" ? "模拟" : "信号"}
                  </button>
                  <button
                    className={`state-button ${strategy.running ? "running" : ""}`}
                    onClick={() => toggleStrategy(strategy)}
                    disabled={strategyBusy === strategy.name}
                  >
                    {strategyBusy === strategy.name ? "更新中" : strategy.running ? "运行中" : "已停止"}
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="paper-panel">
            <div className="section-title">
              <span>模拟盘</span>
              <button className="text-button" onClick={resetPaperAccount} disabled={runnerBusy === "paper-reset"}>
                重置
              </button>
            </div>
            <div className="paper-grid">
              <Metric label="权益" value={`$${formatNumber(paper?.equity, 2)}`} />
              <Metric label="总盈亏" value={`$${formatNumber(paper?.total_pnl, 2)}`} accent />
              <Metric label="未实现" value={`$${formatNumber(paper?.unrealized_pnl, 2)}`} />
              <Metric label="持仓" value={String(paper?.active_positions ?? 0)} />
            </div>
            {paper?.positions.length ? (
              paper.positions.map((position) => (
                <div className="position-row" key={`${position.exchange}-${position.symbol}`}>
                  <div>
                    <strong>{position.symbol}</strong>
                    <span>{position.exchange}</span>
                  </div>
                  <div>
                    <strong>{formatNumber(position.quantity, 6)}</strong>
                    <span>${formatNumber(position.unrealized_pnl, 2)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无模拟持仓</div>
            )}
            <div className="section-title compact-title">
              <span>虚拟成交</span>
              <small>{paper?.orders.length ?? 0}</small>
            </div>
            {paper?.orders.slice(-4).reverse().map((order) => (
              <div className="trade-row" key={order.order_id}>
                <span className={order.side === "buy" ? "buy-text" : "sell-text"}>
                  {order.side === "buy" ? "买" : "卖"}
                </span>
                <strong>{order.symbol}</strong>
                <small>${formatNumber(order.price, 2)}</small>
              </div>
            ))}
          </div>

          <div className="positions">
            <div className="section-title">
              <span>本地持仓记录</span>
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
                <code className={enabledExchanges.includes(item) ? "enabled" : ""} key={item}>
                  {item}
                </code>
              ))}
            </div>
          </div>

          <div className="runtime-grid">
            <Metric label="默认交易所" value={config?.default_exchange ?? "--"} />
            <Metric label="默认合约" value={config?.default_symbol ?? "--"} />
            <Metric label="存储" value={config?.persistence.driver ?? "--"} />
            <Metric label="数据库" value={config?.persistence.path ?? "--"} />
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
