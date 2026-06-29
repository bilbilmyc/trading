/**
 * Top-level HTTP client for the trading backend.
 *
 * `import { api } from "./api"` is the single surface used by pages
 * and contexts. Internally it's a thin re-export shim that composes
 * per-domain API objects (see `marketApi`, `ordersApi`, ...) from
 * sibling modules under `./api/`.
 *
 * When adding a new endpoint, decide which domain it belongs to:
 *   - market data (ticker, klines, ...) → `api/market.ts`
 *   - order placement / cancel          → `api/orders.ts`
 *   - engine / runner / paper          → `api/engine.ts`
 *   - strategy CRUD + signals          → `api/strategies.ts`
 *   - portfolio metrics                → `api/portfolio.ts` (next)
 *   - AI / LLM                        → `api/ai.ts` (next)
 *   - monitor / alerts                 → `api/monitor.ts` (next)
 *   - kill switch + risk settings     → `api/risk.ts` (next)
 *   - custom data sources              → `api/sources.ts` (next)
 *   - shared types (enum aliases)      → `api/_types.ts`
 *   - shared fetch client              → `api/_client.ts`
 */

import { API_BASE, request } from "./api/_client";
import { marketApi } from "./api/market";
import { ordersApi } from "./api/orders";
import { engineApi } from "./api/engine";
import { strategiesApi } from "./api/strategies";
import { portfolioApi } from "./api/portfolio";

// Re-exported so existing `import { Ticker } from "./api"` keeps working
// while the types live next to the methods that return them.
export type {
  ExchangeName,
  Intent,
  Liquidity,
  MarginMode,
  PositionSide,
} from "./api/_types";
export type {
  Ticker,
  ContractMarket,
  RecentTrade,
  Candle,
  OpenOrder,
  FeeRate,
  CostEstimate,
} from "./api/market";
export type { ContractOrderPayload, ContractOrderPreview } from "./api/orders";
export type { EngineStatus } from "./api/engine";
export type {
  StrategyInfo,
  PaperSummary,
  PaperPosition,
  PaperOrder,
  StrategySignal,
  AuditEvent,
  CreateSMAStrategyPayload,
  SignalRunnerStatus,
} from "./api/strategies";
export type { TradeRecord, EquityPoint, LeaderboardEntry } from "./api/portfolio";

// ── Types that still live here (haven't been split yet) ──────────

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

export interface KillSwitchStatus {
  enabled: boolean;
  trading_enabled: boolean;
  risk: { trading_enabled: boolean; daily_pnl: number; current_drawdown: number; orders_last_minute: number; max_orders_per_minute: number };
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

// ── The full API surface, composed of domain partials ─────────────

export const api = {
  baseUrl: API_BASE,
  ...marketApi,
  ...ordersApi,
  ...engineApi,
  ...strategiesApi,
  ...portfolioApi,

  health: () => request<HealthResponse>("/health"),

  config: () => request<AppConfig>("/api/v1/config"),

  exchanges: () => request<{ exchanges: string[]; enabled: string[] }>("/api/v1/exchanges"),

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

  aiAnalyze: (payload: { exchange: string; symbol: string; interval: string; limit: number }) =>
    request<LLMAnalysisResult>("/api/v1/ai/analyze", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

// Allow pages that build custom URLs (e.g. SSE) to call `api.request`.
(api as unknown as { request: typeof request }).request = request;
