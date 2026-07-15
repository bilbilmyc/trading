import { useCallback, useEffect, useState } from "react";
import { ArrowLeftRight } from "lucide-react";
import { useStatus } from "../contexts/StatusContext";
import { useEngine } from "../contexts/EngineContext";
import { api } from "../api";
import { engineApi } from "../api/engine";
import type {
  ContractMarket,
  ContractOrderPayload,
  ContractOrderPreview,
  CostEstimate,
  ExchangeName,
  FeeRate,
  Intent,
  Liquidity,
  MarginMode,
  PositionSide,
  Ticker,
} from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { OrderPanel } from "../components/OrderPanel";
import { MarketPanel } from "../components/MarketPanel";
import { MarketSnapshot } from "../components/MarketSnapshot";
import { PageHeader } from "../components/PageHeader";

export function TradePage() {
  const { apiOnline, lastRefreshedAt } = useStatus();
  const engine = useEngine();
  const [tradingReady, setTradingReady] = useState<boolean | null>(null);

  useEffect(() => {
    if (!apiOnline) return;
    api
      .exchanges()
      .then((r) => {
        const ok = (r.enabled?.length ?? 0) > 0;
        setTradingReady(ok);
      })
      .catch(() => setTradingReady(false));
  }, [apiOnline]);

  if (tradingReady === false) {
    return (
      <div className="page page--trade">
        <PageHeader
          icon={<ArrowLeftRight size={18} />}
          eyebrow="合约下单"
          title="Trade"
          subtitle="人工下单 / 合约预览 / 风险闸门"
        />
        <ErrorPanel
          title="未配置交易交易所"
          message="要执行真实下单，需要在 .env 中配置至少一个交易所的 API Key 并启用 ENABLE_LIVE_TRADING=true。公开市场数据无需 Key，可在「行情」和「数据源」页面查询。"
          action={{ label: "去数据源页", href: "/data" }}
        />
      </div>
    );
  }

  const [exchange, setExchange] = useState<ExchangeName>("binance_usdm");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [contractSearch, setContractSearch] = useState("");
  const [contracts, setContracts] = useState<ContractMarket[]>([]);
  const [contractsLoading, setContractsLoading] = useState(false);
  const [contractsTotal, setContractsTotal] = useState(0);
  const [intent, setIntent] = useState<Intent>("open_long");
  const [quantity, setQuantity] = useState("0.001");
  const [price, setPrice] = useState("100000");
  const [leverage, setLeverage] = useState("3");
  const [orderType, setOrderType] = useState<ContractOrderPayload["order_type"]>("post_only");
  const [marginMode, setMarginMode] = useState<MarginMode>("cross");
  const [positionSide, setPositionSide] = useState<PositionSide>("long");
  const [liquidity, setLiquidity] = useState<Liquidity>("maker");
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [feeRate, setFeeRate] = useState<FeeRate | null>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [orderPreview, setOrderPreview] = useState<ContractOrderPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [message, setMessage] = useState("等待连接后端");
  const [error, setError] = useState("");

  const numericQuantity = Number(quantity);
  const numericPrice = Number(price);
  const notional = numericQuantity * numericPrice;
  const blockedReason = !apiOnline ? "后端离线" : "";

  const [evaluating, setEvaluating] = useState(false);
  const [runnerBusy, setRunnerBusy] = useState("");
  const [toast, setToast] = useState("");

  const onEvaluate = useCallback(async () => {
    if (!engine.engine) return;
    setEvaluating(true);
    setToast("");
    try {
      const r = await engineApi.runSignalCycle();
      setToast(`本轮处理 ${r.processed_strategies} 策略, 产生 ${r.signals.length} 信号`);
      await engine.refresh();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "评估失败");
    } finally {
      setEvaluating(false);
    }
  }, [engine]);

  const onStartRunner = useCallback(async () => {
    setRunnerBusy("start");
    setToast("");
    try {
      await engineApi.startRunner();
      await engine.refresh();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "启动失败");
    } finally {
      setRunnerBusy("");
    }
  }, [engine]);

  const onStopRunner = useCallback(async () => {
    setRunnerBusy("stop");
    setToast("");
    try {
      await engineApi.stopRunner();
      await engine.refresh();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "停止失败");
    } finally {
      setRunnerBusy("");
    }
  }, [engine]);

  const onRunOnce = useCallback(async () => {
    setRunnerBusy("run-once");
    setToast("");
    try {
      await engineApi.runSignalCycle();
      await engine.refresh();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "执行失败");
    } finally {
      setRunnerBusy("");
    }
  }, [engine]);

  const onResetPaper = useCallback(async () => {
    if (!window.confirm("确定重置模拟盘? 所有模拟持仓将被清空。")) return;
    setRunnerBusy("paper-reset");
    setToast("");
    try {
      await engineApi.resetPaper();
      await engine.refresh();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "重置失败");
    } finally {
      setRunnerBusy("");
    }
  }, [engine]);

  const refreshContracts = useCallback(async () => {
    if (!apiOnline) return;
    setContractsLoading(true);
    try {
      const result = await api.contracts(exchange, contractSearch, 200);
      setContracts(result.contracts);
      setContractsTotal(result.total);
    } catch {
      setContracts([]);
    } finally {
      setContractsLoading(false);
    }
  }, [apiOnline, contractSearch, exchange]);

  const refreshTickerAndFee = useCallback(async () => {
    if (!apiOnline || !symbol) return;
    try {
      const [t, fee, cost] = await Promise.all([
        api.ticker(exchange, symbol),
        api.feeRate(exchange, symbol),
        numericQuantity > 0 && numericPrice > 0
          ? api.costEstimate(exchange, symbol, numericQuantity, numericPrice, liquidity)
          : Promise.resolve(null),
      ]);
      setTicker(t);
      setFeeRate(fee);
      if (cost) setEstimate(cost);
    } catch {
      /* keep last */
    }
  }, [apiOnline, exchange, symbol, liquidity, numericQuantity, numericPrice]);

  useEffect(() => { refreshContracts(); }, [refreshContracts]);
  useEffect(() => { refreshTickerAndFee(); }, [refreshTickerAndFee]);

  function buildPayload(clientOrderId?: string): ContractOrderPayload {
    const payload: ContractOrderPayload = {
      exchange, symbol, intent,
      quantity: numericQuantity,
      order_type: orderType,
      margin_mode: marginMode,
      position_side: positionSide,
      reduce_only: intent === "close_long" || intent === "close_short",
    };
    if (orderType !== "market") payload.price = numericPrice;
    const lev = Number(leverage);
    if (lev > 0) payload.leverage = lev;
    if (clientOrderId) payload.client_order_id = clientOrderId;
    return payload;
  }

  async function onPreview() {
    if (!apiOnline || !symbol) return;
    setPreviewBusy(true);
    setError("");
    try {
      const preview = await api.previewContractOrder(buildPayload());
      setOrderPreview(preview);
      setMessage(`已生成下单预览：${preview.client_order_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成下单预览失败");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function onSubmit() {
    if (!apiOnline) return;
    setBusy(true);
    try {
      const payload = buildPayload(orderPreview?.client_order_id);
      const preview = await api.previewContractOrder(payload);
      if (orderType === "market" && !window.confirm("Market 单会直接吃单成交，确认继续？")) return;
      if (!window.confirm(`确认提交订单？\n订单号：${preview.client_order_id}\n名义价值：$${preview.notional?.toFixed(2) ?? "--"}`)) return;
      const result = await api.placeContractOrder({ ...payload, client_order_id: preview.client_order_id });
      setMessage(`订单已提交：${String(result.order_id ?? "pending")}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "下单失败");
    } finally {
      setBusy(false);
    }
  }

  // Numeric values for the v0.4 baseline strip — same data the old KPIHero
  // had, but in <MarketSnapshot> shape (hairline card, tabular nums).
  const priceChangePct = ticker?.price_change_pct_24h ?? 0;
  const volumeUsdtM = ticker ? Number(ticker.quote_volume_24h ?? 0) / 1e6 : 0;

  return (
    <div className="page page--trade stack">
      <PageHeader
        icon={<ArrowLeftRight size={18} />}
        eyebrow="人工下单"
        title="下单"
        subtitle="合约预览 · 一键提交 · 预览后才下单"
        freshness={{ at: lastRefreshedAt, label: "状态" }}
      />

      {/* v0.4 stats strip — hairline cards, tabular figures. */}
      <div className="market-snap-strip">
        <MarketSnapshot
          label={`${symbol} 最新价`}
          value={
            ticker
              ? `$${Number(ticker.last_price).toLocaleString("en-US", { maximumFractionDigits: 2 })}`
              : "$—"
          }
          icon={<ArrowLeftRight size={12} />}
          delta={
            ticker
              ? {
                  value: `${priceChangePct >= 0 ? "+" : ""}${(priceChangePct * 100).toFixed(2)}%`,
                  tone: priceChangePct >= 0 ? "positive" : "negative",
                }
              : undefined
          }
          sparkline={[10, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 16]}
          hint="24h"
        />
        <MarketSnapshot
          label="24h 成交额"
          value={ticker ? `$${volumeUsdtM.toFixed(1)}M` : "—"}
          icon={<ArrowLeftRight size={12} />}
          sparkline={[8, 9, 8, 10, 11, 12, 11, 13, 12, 14, 13, 15]}
          hint="USDT"
        />
        <MarketSnapshot
          label="Maker / Taker"
          value={
            feeRate
              ? `${(feeRate.maker * 100).toFixed(3)}% / ${(feeRate.taker * 100).toFixed(3)}%`
              : "— / —"
          }
          icon={<ArrowLeftRight size={12} />}
          hint="费率"
        />
        <MarketSnapshot
          label="名义价值"
          value={`$${notional.toLocaleString("en-US", { maximumFractionDigits: 2 })}`}
          icon={<ArrowLeftRight size={12} />}
          sparkline={Array.from({ length: 12 }, (_, i) => notional / 1000 + Math.sin(i) * 2)}
          hint={`数量 ${quantity}`}
        />
      </div>

      {/* Symbol bar — compact command strip. */}
      <div className="symbol-bar">
        <span className="symbol-bar__field">
          <span className="symbol-bar__field-label">EXCHANGE</span>
          <span className="symbol-bar__field-value">{exchange.replace("_", " ")}</span>
        </span>
        <span className="symbol-bar__field">
          <span className="symbol-bar__field-label">SYMBOL</span>
          <span className="symbol-bar__field-value num">{symbol}</span>
        </span>
        <span className="symbol-bar__field">
          <span className="symbol-bar__field-label">SIDE</span>
          <span className="symbol-bar__field-value">{intent}</span>
        </span>
        <span className="symbol-bar__field">
          <span className="symbol-bar__field-label">LEV</span>
          <span className="symbol-bar__field-value num">{leverage}x</span>
        </span>
        <span className="symbol-bar__price">
          {ticker ? (
            <>
              <span className="symbol-bar__price-now num">
                ${Number(ticker.last_price).toLocaleString("en-US", { maximumFractionDigits: 2 })}
              </span>
              <span
                className={`symbol-bar__price-delta ${
                  priceChangePct >= 0
                    ? "symbol-bar__price-delta--up"
                    : "symbol-bar__price-delta--down"
                }`}
              >
                {priceChangePct >= 0 ? "▲" : "▼"}{" "}
                {(priceChangePct * 100).toFixed(2)}%
              </span>
            </>
          ) : (
            <span className="text-muted num">—</span>
          )}
        </span>
      </div>

      <div className="terminal-grid">
        <OrderPanel
          exchange={exchange}
          onExchangeChange={setExchange}
          symbol={symbol}
          onSymbolChange={setSymbol}
          contractSearch={contractSearch}
          onContractSearchChange={setContractSearch}
          contracts={contracts}
          contractsLoading={contractsLoading}
          contractsTotal={contractsTotal}
          onContractSelect={async (c) => {
            setSymbol(c.symbol);
            if (c.min_quantity) setQuantity(String(c.min_quantity));
          }}
          intent={intent}
          onIntentChange={setIntent}
          quantity={quantity}
          onQuantityChange={setQuantity}
          price={price}
          onPriceChange={setPrice}
          leverage={leverage}
          onLeverageChange={setLeverage}
          orderType={orderType}
          onOrderTypeChange={(v) => {
            setOrderType(v);
            if (v === "market" || v === "ioc" || v === "fok") setLiquidity("taker");
          }}
          marginMode={marginMode}
          onMarginModeChange={setMarginMode}
          positionSide={positionSide}
          onPositionSideChange={setPositionSide}
          preview={orderPreview}
          previewBusy={previewBusy}
          onPreview={onPreview}
          onSubmit={onSubmit}
          busy={busy}
          blockedReason={blockedReason}
          apiOnline={apiOnline}
          notice={error ? { tone: "error", message: error } : { tone: "info", message }}
        />

        <MarketPanel
          symbol={symbol}
          ticker={ticker}
          trades={[]}
          openOrders={[]}
          feeRate={feeRate}
          estimate={estimate}
          liquidity={liquidity}
          onLiquidityChange={setLiquidity}
          strategyCount={engine.strategies.length}
          signalCount={engine.signals.length}
          runnerRunning={engine.engine?.signal_runner?.running ?? false}
          onEvaluate={onEvaluate}
          onStartRunner={onStartRunner}
          onStopRunner={onStopRunner}
          onRunOnce={onRunOnce}
          onResetPaper={onResetPaper}
          evaluating={evaluating}
          runnerBusy={runnerBusy}
          signals={engine.signals.slice(0, 5)}
          notional={notional}
        />
      </div>
    </div>
  );
}
