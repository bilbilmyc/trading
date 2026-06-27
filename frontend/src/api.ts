export type ExchangeName = "binance_usdm" | "bitget_usdt_futures" | "okx_swap";
export type Intent = "open_long" | "close_long" | "open_short" | "close_short";
export type Liquidity = "maker" | "taker";
export type MarginMode = "cross" | "isolated";
export type PositionSide = "net" | "long" | "short";

export interface HealthResponse {
  status: string;
  env: string;
}

export interface AppConfig {
  app_name: string;
  app_env: string;
  default_exchange: string;
  default_symbol: string;
  live_trading_enabled: boolean;
  frontend_static_dir: string;
  persistence: { driver: string; path: string };
  exchanges: Record<string, { enabled: boolean; use_testnet: boolean; has_api_key: boolean }>;
  exchange_capabilities: Record<string, ExchangeCapabilities>;
  risk: Record<string, number>;
}

export interface ExchangeCapabilities {
  supports_hedge_mode: boolean;
  supports_post_only: boolean;
  requires_symbol_for_cancel_all: boolean;
  supports_public_fee_lookup: boolean;
  supports_private_fee_lookup: boolean;
}

export interface EngineStatus {
  running: boolean;
  exchanges: string[];
  strategies: string[];
  strategy_details?: StrategyInfo[];
  recent_signals?: StrategySignal[];
  signal_runner?: SignalRunnerStatus;
  paper?: PaperSummary;
  risk: {
    trading_enabled: boolean;
    daily_pnl: number;
    current_drawdown: number;
    orders_last_minute: number;
    max_orders_per_minute: number;
  };
  positions: {
    total_unrealized_pnl: number;
    total_realized_pnl: number;
    total_pnl: number;
    active_positions: number;
    positions: Array<{
      symbol: string;
      exchange: string;
      quantity: number;
      avg_entry_price: number;
      current_price: number;
      unrealized_pnl: number;
      pnl_pct: number;
    }>;
  };
  timestamp: string;
}

export interface KillSwitchStatus {
  enabled: boolean;
  trading_enabled: boolean;
  risk: EngineStatus["risk"];
}

export interface SignalRunnerStatus {
  running: boolean;
  poll_seconds?: number | null;
  last_cycle_at?: string | null;
  last_error?: string | null;
  cycles: number;
  signals_generated: number;
}

export interface PaperPosition {
  exchange: string;
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  updated_at: string;
}

export interface PaperOrder {
  order_id: string;
  exchange: string;
  strategy: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  realized_pnl: number;
  status: string;
  timestamp: string;
  signal_metadata: Record<string, unknown>;
}

export interface PaperSummary {
  enabled: boolean;
  initial_cash: number;
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  fee_rate: number;
  active_positions: number;
  positions: PaperPosition[];
  orders: PaperOrder[];
}

export interface StrategyInfo {
  name: string;
  class_name: string;
  initialized_at: string;
  running: boolean;
  exchange?: string | null;
  symbol?: string | null;
  interval?: string;
  mode?: string;
  updated_at?: string | null;
  parameters: Record<string, string | number | boolean | null>;
}

export interface CreateSMAStrategyPayload {
  name?: string;
  exchange: ExchangeName;
  symbol: string;
  interval: string;
  short_window: number;
  long_window: number;
  min_data_points?: number;
  enabled: boolean;
  mode: "signal" | "paper";
}

export interface StrategySignal {
  exchange: string;
  strategy: string;
  symbol: string;
  action: string;
  strength: number;
  quantity?: number | null;
  price?: number | null;
  order_type: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  metadata: Record<string, unknown>;
  actionable: boolean;
  timestamp: string;
}

export interface AuditEvent {
  id: number;
  category: "order" | "risk" | string;
  event_type: string;
  level: "info" | "warning" | "error" | string;
  exchange?: string | null;
  symbol?: string | null;
  strategy?: string | null;
  order_id?: string | null;
  message: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface FeeRate {
  exchange: string;
  symbol: string;
  maker: number;
  taker: number;
  timestamp: string;
  raw: Record<string, unknown>;
}

export interface LLMAnalysisResult {
  decision: string;
  confidence: number;
  reason: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  risk_level: string;
  risk_note: string;
  model?: string;
  analysis_time?: string;
  candle_count?: number;
  cache_hit?: boolean;
  error_kind?: string | null;
}

export interface CostEstimate {
  exchange: string;
  symbol: string;
  notional: number;
  liquidity: Liquidity;
  fee_rate: number;
  estimated_fee: number;
  raw_fee: FeeRate;
  notes: string[];
}

export interface Ticker {
  symbol: string;
  exchange: string;
  last_price: number;
  bid_price?: number | null;
  ask_price?: number | null;
  high_24h?: number;
  low_24h?: number;
  volume_24h?: number;
  quote_volume_24h?: number;
  price_change_24h?: number;
  price_change_pct_24h?: number;
  timestamp: string;
}

export interface ContractMarket {
  exchange: ExchangeName;
  symbol: string;
  base_asset: string;
  quote_asset: string;
  status: string;
  contract_type: string;
  price_tick?: number | null;
  quantity_step?: number | null;
  min_quantity?: number | null;
  raw: Record<string, unknown>;
}

export interface RecentTrade {
  symbol: string;
  exchange: string;
  trade_id: string;
  price: number;
  quantity: number;
  side: "buy" | "sell" | string;
  timestamp: string;
}

export interface Candle {
  open_time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface OpenOrder {
  order_id?: string;
  orderId?: string | number;
  symbol?: string;
  side?: string;
  price?: string | number;
  quantity?: string | number;
  origQty?: string | number;
  status?: string;
  raw?: Record<string, unknown>;
}

export interface ContractOrderPayload {
  exchange: ExchangeName;
  symbol: string;
  intent: Intent;
  quantity: number;
  order_type: "market" | "limit" | "post_only" | "ioc" | "fok";
  price?: number;
  margin_mode: MarginMode;
  position_side: PositionSide;
  leverage?: number;
  reduce_only?: boolean;
  client_order_id?: string;
}

export interface ContractOrderPreview {
  exchange: ExchangeName;
  symbol: string;
  intent: Intent;
  side: string;
  quantity: number;
  order_type: string;
  price: number;
  notional: number;
  leverage: number;
  initial_margin: number;
  margin_mode: MarginMode;
  position_side: PositionSide;
  reduce_only: boolean;
  liquidity: Liquidity;
  fee_rate?: number | null;
  estimated_fee?: number | null;
  client_order_id: string;
  live_trading_enabled: boolean;
  liquidation_risk_note: string;
  notes: string[];
  request: ContractOrderPayload;
}

function resolveApiBase() {
  if (import.meta.env.VITE_API_BASE_URL) return import.meta.env.VITE_API_BASE_URL;
  if (window.location.port === "5173") return "http://127.0.0.1:8000";
  return window.location.origin;
}

const API_BASE = resolveApiBase();

function formatApiError(message: unknown, fallback: string) {
  if (!message) return fallback;
  if (typeof message === "string") return message;
  if (Array.isArray(message)) return JSON.stringify(message);
  if (typeof message === "object") {
    const maybeMessage = (message as { message?: unknown }).message;
    if (typeof maybeMessage === "string") return maybeMessage;
    return JSON.stringify(message);
  }
  return String(message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(formatApiError(payload?.detail, response.statusText));
  }
  return payload as T;
}

export const api = {
  baseUrl: API_BASE,

  health: () => request<HealthResponse>("/health"),

  config: () => request<AppConfig>("/api/v1/config"),

  exchanges: () => request<{ exchanges: string[]; enabled: string[] }>("/api/v1/exchanges"),

  engineStatus: () => request<EngineStatus>("/api/v1/engine/status"),

  strategies: () => request<{ strategies: StrategyInfo[] }>("/api/v1/strategies"),

  createSmaStrategy: (payload: CreateSMAStrategyPayload) =>
    request<{ strategy: StrategyInfo }>("/api/v1/strategies/sma", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startStrategy: (name: string) =>
    request<{ strategy: StrategyInfo }>(`/api/v1/strategies/${encodeURIComponent(name)}/start`, {
      method: "POST",
    }),

  stopStrategy: (name: string) =>
    request<{ strategy: StrategyInfo }>(`/api/v1/strategies/${encodeURIComponent(name)}/stop`, {
      method: "POST",
    }),

  setStrategyMode: (name: string, mode: "signal" | "paper") =>
    request<{ strategy: StrategyInfo }>(`/api/v1/strategies/${encodeURIComponent(name)}/mode`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),

  paper: () => request<PaperSummary>("/api/v1/paper"),

  resetPaper: (initial_cash?: number) =>
    request<PaperSummary>("/api/v1/paper/reset", {
      method: "POST",
      body: JSON.stringify({ initial_cash }),
    }),

  runnerStatus: () => request<SignalRunnerStatus>("/api/v1/runner/status"),

  startRunner: (poll_seconds = 60, candle_limit = 80) =>
    request<SignalRunnerStatus>("/api/v1/runner/start", {
      method: "POST",
      body: JSON.stringify({ poll_seconds, candle_limit }),
    }),

  stopRunner: () =>
    request<SignalRunnerStatus>("/api/v1/runner/stop", {
      method: "POST",
    }),

  runSignalCycle: (poll_seconds = 60, candle_limit = 80) =>
    request<{
      processed_strategies: number;
      signals: StrategySignal[];
      errors: Array<{ strategy: string; error: string }>;
      status: SignalRunnerStatus;
    }>("/api/v1/runner/run-once", {
      method: "POST",
      body: JSON.stringify({ poll_seconds, candle_limit }),
    }),

  recentSignals: (limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) });
    return request<{ signals: StrategySignal[] }>(`/api/v1/signals/recent?${params}`);
  },

  recentEvents: (limit = 20, category?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (category) params.set("category", category);
    return request<{ events: AuditEvent[] }>(`/api/v1/events/recent?${params}`);
  },

  killSwitchStatus: () => request<KillSwitchStatus>("/api/v1/risk/kill-switch"),

  setKillSwitch: (enabled: boolean, reason: string) =>
    request<{ enabled: boolean; trading_enabled: boolean }>("/api/v1/risk/kill-switch", {
      method: "POST",
      body: JSON.stringify({ enabled, reason }),
    }),
  toggleLiveTrading: (enabled: boolean) =>
    request<{ live_trading_enabled: boolean }>("/api/v1/settings/live-trading", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  evaluateSignals: (exchange: ExchangeName, symbol: string, interval = "1m", limit = 80) => {
    const params = new URLSearchParams({ exchange, symbol, interval, limit: String(limit) });
    return request<{
      exchange: string;
      symbol: string;
      interval: string;
      candles_processed: number;
      signals: StrategySignal[];
      recent_signals: StrategySignal[];
    }>(`/api/v1/signals/evaluate?${params}`, { method: "POST" });
  },

  ticker: (exchange: ExchangeName, symbol: string) =>
    request<Ticker>(`/api/v1/ticker/${exchange}/${encodeURIComponent(symbol)}`),

  klines: (exchange: ExchangeName, symbol: string, interval = "1h", limit = 80) => {
    const params = new URLSearchParams({ interval, limit: String(limit) });
    return request<Candle[]>(`/api/v1/klines/${exchange}/${encodeURIComponent(symbol)}?${params}`);
  },

  contracts: (exchange: ExchangeName, search = "", limit = 200) => {
    const params = new URLSearchParams({ quote_asset: "USDT", search, limit: String(limit) });
    return request<{ contracts: ContractMarket[]; total: number }>(`/api/v1/contracts/${exchange}?${params}`);
  },

  recentTrades: (exchange: ExchangeName, symbol: string, limit = 8) => {
    const params = new URLSearchParams({ limit: String(limit) });
    return request<RecentTrade[]>(`/api/v1/trades/${exchange}/${encodeURIComponent(symbol)}?${params}`);
  },

  openOrders: (exchange: ExchangeName, symbol: string) => {
    const params = new URLSearchParams({ symbol });
    return request<OpenOrder[]>(`/api/v1/orders/${exchange}/open?${params}`);
  },

  feeRate: (exchange: ExchangeName, symbol: string) =>
    request<FeeRate>(`/api/v1/contracts/${exchange}/${encodeURIComponent(symbol)}/fee-rate`),

  costEstimate: (
    exchange: ExchangeName,
    symbol: string,
    quantity: number,
    price: number,
    liquidity: Liquidity,
  ) => {
    const params = new URLSearchParams({
      quantity: String(quantity),
      price: String(price),
      liquidity,
    });
    return request<CostEstimate>(
      `/api/v1/contracts/${exchange}/${encodeURIComponent(symbol)}/cost-estimate?${params}`,
    );
  },

  portfolioMetrics: () =>
    request<{
      sharpe_ratio: number;
      sortino_ratio: number;
      max_drawdown: number;
      profit_factor: number;
      expectancy: number;
      win_rate: number;
      total_trades: number;
      annualized_return: number;
    }>("/api/v1/portfolio/metrics"),

  strategiesLeaderboard: () =>
    request<{ strategies: Array<{ rank: number; strategy: string; score: number }> }>(
      "/api/v1/strategies/leaderboard"
    ),

  aiAnalyze: (payload: { exchange: string; symbol: string; interval: string; limit: number }) =>
    request<LLMAnalysisResult>("/api/v1/ai/analyze", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  placeContractOrder: (payload: ContractOrderPayload) =>
    request<Record<string, unknown>>("/api/v1/contracts/order", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  previewContractOrder: (payload: ContractOrderPayload) =>
    request<ContractOrderPreview>("/api/v1/contracts/order/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
