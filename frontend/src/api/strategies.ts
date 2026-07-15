/**
 * Strategy CRUD, signals, events, LLM strategy management.
 *
 * StrategyInfo / PaperSummary are defined here because they're shared
 * between this module and the engine module. EngineStatus references
 * them, so engine.ts imports them from here.
 */

import type { ExchangeName } from "./_types";
import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

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

export interface SignalRunnerStatus {
  running: boolean;
  poll_seconds?: number | null;
  last_cycle_at?: string | null;
  last_error?: string | null;
  cycles: number;
  signals_generated: number;
}

// ── Methods ──────────────────────────────────────────────────────

export const strategiesApi = {
  strategies: () => request<{ strategies: StrategyInfo[] }>("/api/v1/strategies"),

  createSmaStrategy: (payload: CreateSMAStrategyPayload) =>
    request<{ strategy: StrategyInfo }>("/api/v1/strategies/sma", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startStrategy: (name: string) =>
    request<{ strategy: StrategyInfo }>(
      `/api/v1/strategies/${encodeURIComponent(name)}/start`,
      { method: "POST" },
    ),

  stopStrategy: (name: string) =>
    request<{ strategy: StrategyInfo }>(
      `/api/v1/strategies/${encodeURIComponent(name)}/stop`,
      { method: "POST" },
    ),

  setStrategyMode: (name: string, mode: "signal" | "paper") =>
    request<{ strategy: StrategyInfo }>(
      `/api/v1/strategies/${encodeURIComponent(name)}/mode`,
      { method: "POST", body: JSON.stringify({ mode }) },
    ),

  recentSignals: (limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) });
    return request<{ signals: StrategySignal[] }>(
      `/api/v1/signals/recent?${params.toString()}`,
    );
  },

  recentEvents: (opts: { limit?: number; category?: string; eventType?: string; minutes?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.category) params.set("category", opts.category);
    if (opts.eventType) params.set("event_type", opts.eventType);
    if (opts.minutes) params.set("minutes", String(opts.minutes));
    const qs = params.toString();
    return request<{ events: AuditEvent[]; count: number }>(
      `/api/v1/events/recent${qs ? `?${qs}` : ""}`,
    );
  },

  evaluateSignals: (
    exchange: ExchangeName,
    symbol: string,
    interval = "1m",
    limit = 80,
  ) => {
    const params = new URLSearchParams({ exchange, symbol, interval, limit: String(limit) });
    return request<{ signals: StrategySignal[]; recent_signals: StrategySignal[] }>(
      `/api/v1/signals/evaluate?${params.toString()}`,
      { method: "POST" },
    );
  },
};
