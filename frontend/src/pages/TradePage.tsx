import { useCallback, useEffect, useState } from "react";
import { ArrowLeftRight } from "lucide-react";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
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
import { PageHeader } from "../components/PageHeader";

export function TradePage() {
  const { apiOnline } = useStatus();
  const [tradingReady, setTradingReady] = useState<boolean | null>(null);

  useEffect(() => {
    if (!apiOnline) return;
    api
      .exchanges()
      .then((r) => {
        // Trading ready if any enabled exchange has API key + enable_live_trading.
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
  const blockedReason = !apiOnline
    ? "后端离线"
    : "";

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

  return (
    <div className="page page--trade">
      <PageHeader
        icon={<ArrowLeftRight size={18} />}
        eyebrow="人工下单"
        title="下单"
        subtitle="合约预览 · 一键提交 · 预览后才下单"
      />

      <div className="page__grid page__grid--two-thirds">
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
          strategyCount={0}
          signalCount={0}
          runnerRunning={false}
          onEvaluate={async () => {}}
          onStartRunner={async () => {}}
          onStopRunner={async () => {}}
          onRunOnce={async () => {}}
          onResetPaper={async () => {}}
          evaluating={false}
          runnerBusy=""
          signals={[]}
          notional={notional}
        />
      </div>
    </div>
  );
}