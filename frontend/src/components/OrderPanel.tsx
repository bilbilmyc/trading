import { ArrowDownRight, ArrowUpRight, Send, ShieldAlert } from "lucide-react";
import type {
  ContractMarket,
  ContractOrderPayload,
  ContractOrderPreview,
  ExchangeName,
  Intent,
  Liquidity,
  MarginMode,
  PositionSide,
} from "../api";
import { buildSymbolOptions } from "../utils/symbols";
import { AutocompleteInput } from "./AutocompleteInput";
import { EmptyState, Metric, SectionTitle } from "./atoms";

const EXCHANGE_OPTIONS: Array<{ value: ExchangeName; label: string }> = [
  { value: "binance_usdm", label: "Binance U 本位" },
  { value: "bitget_usdt_futures", label: "Bitget U 本位" },
  { value: "okx_swap", label: "OKX 永续" },
];

const INTENTS: Array<{ value: Intent; label: string; tone: "buy" | "sell" }> = [
  { value: "open_long", label: "买入开多", tone: "buy" },
  { value: "close_long", label: "卖出平多", tone: "sell" },
  { value: "open_short", label: "卖出开空", tone: "sell" },
  { value: "close_short", label: "买入平空", tone: "buy" },
];

const ORDER_TYPES: Array<{ value: ContractOrderPayload["order_type"]; label: string }> = [
  { value: "post_only", label: "只挂单" },
  { value: "limit", label: "限价单" },
  { value: "market", label: "市价单" },
  { value: "ioc", label: "IOC" },
  { value: "fok", label: "FOK" },
];

const POSITION_SIDES: Array<{ value: PositionSide; label: string }> = [
  { value: "long", label: "多仓" },
  { value: "short", label: "空仓" },
  { value: "net", label: "单向持仓" },
];

const LEVERAGE_OPTIONS = ["1", "2", "3", "5", "10", "20", "25", "50", "75", "100", "125"].map((value) => ({
  value,
  label: `${value}x`,
  description: "杠杆预设",
}));

const MARGIN_MODES: Array<{ value: MarginMode; label: string }> = [
  { value: "cross", label: "全仓" },
  { value: "isolated", label: "逐仓" },
];

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(value);
}

function isCloseIntent(intent: Intent): boolean {
  return intent === "close_long" || intent === "close_short";
}

function formatQuantitySeed(market: ContractMarket | undefined): string {
  if (!market?.min_quantity || market.min_quantity <= 0) return "1";
  return String(market.min_quantity);
}

interface OrderPanelProps {
  exchange: ExchangeName;
  onExchangeChange: (value: ExchangeName) => void;
  symbol: string;
  onSymbolChange: (value: string) => void;
  contractSearch: string;
  onContractSearchChange: (value: string) => void;
  contracts: ContractMarket[];
  contractsLoading: boolean;
  contractsTotal: number;
  onContractSelect: (contract: ContractMarket) => void;
  intent: Intent;
  onIntentChange: (intent: Intent) => void;
  quantity: string;
  onQuantityChange: (value: string) => void;
  price: string;
  onPriceChange: (value: string) => void;
  leverage: string;
  onLeverageChange: (value: string) => void;
  orderType: ContractOrderPayload["order_type"];
  onOrderTypeChange: (value: ContractOrderPayload["order_type"]) => void;
  marginMode: MarginMode;
  onMarginModeChange: (value: MarginMode) => void;
  positionSide: PositionSide;
  onPositionSideChange: (value: PositionSide) => void;
  preview: ContractOrderPreview | null;
  previewBusy: boolean;
  onPreview: () => void;
  onSubmit: () => void;
  busy: boolean;
  blockedReason: string;
  apiOnline: boolean;
  notice: { tone: "error" | "info"; message: string };
}

export function OrderPanel(props: OrderPanelProps) {
  const numericQuantity = Number(props.quantity);
  const numericPrice = Number(props.price);
  const canPreview = props.apiOnline && Boolean(props.symbol) && numericQuantity > 0;
  const symbolOptions = buildSymbolOptions(props.contracts.map((contract) => contract.symbol));
  const contractSearchOptions = props.contracts.map((contract) => ({
    value: contract.symbol,
    description: `${contract.base_asset} / ${contract.quote_asset}`,
    keywords: [contract.base_asset, contract.quote_asset],
  }));

  return (
    <section className="panel panel--order">
      <SectionTitle title="下单面板" subtitle="合约方向 · 数量 · 杠杆" />
      <div className="form-grid">
        <label className="field">
          <span>交易所</span>
          <select
            value={props.exchange}
            onChange={(e) => props.onExchangeChange(e.target.value as ExchangeName)}
          >
            {EXCHANGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>合约代码</span>
          <AutocompleteInput
            value={props.symbol}
            onChange={(value) => props.onSymbolChange(value.toUpperCase())}
            options={symbolOptions}
            placeholder="输入 BTC、ETH、SOL…"
            aria-label="合约代码"
          />
        </label>
      </div>

      <label className="field">
        <span>搜索合约 · {props.contractsLoading ? "加载中" : `${props.contractsTotal} 个`}</span>
        <AutocompleteInput
          placeholder="输入 BTC、ETH、SOL…"
          value={props.contractSearch}
          onChange={props.onContractSearchChange}
          options={contractSearchOptions.length ? contractSearchOptions : symbolOptions}
          onOptionSelect={(option) => {
            const contract = props.contracts.find((item) => item.symbol === option.value);
            if (contract) props.onContractSelect(contract);
            else props.onSymbolChange(option.value);
          }}
          aria-label="搜索合约"
        />
      </label>

      <div className="market-picker">
        {props.contracts.slice(0, 12).map((c) => (
          <button
            key={c.symbol}
            className={props.symbol === c.symbol ? "market-picker__chip active" : "market-picker__chip"}
            onClick={() => props.onContractSelect(c)}
            type="button"
          >
            <strong>{c.base_asset}</strong>
            <small>{c.symbol}</small>
          </button>
        ))}
        {!props.contracts.length && <EmptyState>没有匹配的合约</EmptyState>}
      </div>

      <div className="intent-grid">
        {INTENTS.map((item) => (
          <button
            key={item.value}
            className={`intent-chip intent-chip--${item.tone} ${props.intent === item.value ? "active" : ""}`}
            onClick={() => props.onIntentChange(item.value)}
            type="button"
          >
            {item.tone === "buy" ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <div className="form-grid">
        <label className="field">
          <span>下单数量</span>
          <input
            value={props.quantity}
            onChange={(e) => props.onQuantityChange(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <label className="field">
          <span>委托价格</span>
          <input
            value={props.price}
            onChange={(e) => props.onPriceChange(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <label className="field">
          <span>杠杆倍数</span>
          <AutocompleteInput
            value={props.leverage}
            onChange={props.onLeverageChange}
            options={LEVERAGE_OPTIONS}
            inputMode="numeric"
            placeholder="例如 10"
            aria-label="杠杆倍数"
          />
        </label>
        <label className="field">
          <span>保证金</span>
          <select
            value={props.marginMode}
            onChange={(e) => props.onMarginModeChange(e.target.value as MarginMode)}
          >
            {MARGIN_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>订单类型</span>
          <select
            value={props.orderType}
            onChange={(e) => props.onOrderTypeChange(e.target.value as ContractOrderPayload["order_type"])}
          >
            {ORDER_TYPES.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>仓位方向</span>
          <select
            value={props.positionSide}
            onChange={(e) => props.onPositionSideChange(e.target.value as PositionSide)}
          >
            {POSITION_SIDES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="action-row">
        <button
          className="action action--secondary"
          onClick={props.onPreview}
          disabled={props.previewBusy || !canPreview}
          type="button"
        >
          {props.previewBusy ? "预览中..." : "生成预览"}
        </button>
        <button
          className="action action--primary"
          onClick={props.onSubmit}
          disabled={props.busy || Boolean(props.blockedReason)}
          type="button"
        >
          <Send size={16} />
          {props.busy ? "提交中..." : props.blockedReason ? props.blockedReason : "预览后提交"}
        </button>
      </div>

      {props.preview && (
        <div className="preview-card">
          <SectionTitle title="下单预览" subtitle={props.preview.client_order_id} />
          <div className="preview-grid">
            <Metric label="名义价值" value={`$${formatNumber(props.preview.notional)}`} tone="muted" />
            <Metric label="初始保证金" value={`$${formatNumber(props.preview.initial_margin)}`} tone="muted" />
            <Metric
              label="预估手续费"
              value={`$${formatNumber(props.preview.estimated_fee ?? undefined, 4)}`}
              tone="warning"
            />
            <Metric label="Reduce Only" value={props.preview.reduce_only ? "是" : "否"} tone="muted" />
          </div>
          {props.preview.liquidation_risk_note && (
            <p className="preview-note">{props.preview.liquidation_risk_note}</p>
          )}
        </div>
      )}

      {props.notice.message && (
        <div className={`notice notice--${props.notice.tone}`}>
          <ShieldAlert size={16} />
          <span>{props.notice.message}</span>
        </div>
      )}
    </section>
  );
}