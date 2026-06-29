export type ExchangeName = "binance_usdm" | "bitget_usdt_futures" | "okx_swap";
export type Intent = "open_long" | "close_long" | "open_short" | "close_short";
export type Liquidity = "maker" | "taker";
export type MarginMode = "cross" | "isolated";
export type PositionSide = "net" | "long" | "short";

import { API_BASE, request } from "./api/_client";
import {
  marketApi,
  type Ticker,
  type ContractMarket,
  type RecentTrade,
  type Candle,
  type OpenOrder,
  type FeeRate,
  type CostEstimate,
} from "./api/market";

// Re-exported from the market module so existing `import { Ticker } from "./api"`
// keeps working while the types live next to the methods that return them.
export type { Ticker, ContractMarket, RecentTrade, Candle, OpenOrder, FeeRate, CostEstimate };

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

export const api = {
  baseUrl: API_BASE,
  ...marketApi,

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

  closePosition: (payload: { exchange: string; symbol: string; exit_quantity?: number }) =>
    request<{ closed_quantity: number; order: Record<string, unknown> }>(
      "/api/v1/positions/close",
      { method: "POST", body: JSON.stringify(payload) }
    ),

  portfolioEquityCurves: () =>
    request<{ curves: Record<string, Array<{ timestamp: string; equity: number }>> }>(
      "/api/v1/portfolio/equity-curves"
    ),

  tradeHistory: (params: { limit?: number; strategy?: string; exchange?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.limit) search.set("limit", String(params.limit));
    if (params.strategy) search.set("strategy", params.strategy);
    if (params.exchange) search.set("exchange", params.exchange);
    const qs = search.toString();
    return request<{
      trades: Array<{
        id: string;
        strategy: string;
        exchange: string;
        symbol: string;
        side: string;
        quantity: number;
        entry_price: number;
        exit_price: number | null;
        pnl: number;
        opened_at: string;
        closed_at: string | null;
        status: string;
      }>;
    }>(`/api/v1/trade-history${qs ? `?${qs}` : ""}`);
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
