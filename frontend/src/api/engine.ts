/**
 * Engine status, signal runner, paper trading, storage endpoints.
 *
 * "Engine" here is the long-running TradingEngine in the backend that
 * drives all strategies. EngineStatus aggregates its current state for
 * the UI; the other methods are controls.
 */

import type { StrategyInfo, StrategySignal, PaperSummary, SignalRunnerStatus } from "./strategies";
import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

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

// ── Methods ──────────────────────────────────────────────────────

export const engineApi = {
  engineStatus: () => request<EngineStatus>("/api/v1/engine/status"),

  runnerStatus: () => request<SignalRunnerStatus>("/api/v1/runner/status"),

  startRunner: (poll_seconds = 60, candle_limit = 80) =>
    request<SignalRunnerStatus>("/api/v1/runner/start", {
      method: "POST",
      body: JSON.stringify({ poll_seconds, candle_limit }),
    }),

  stopRunner: () =>
    request<SignalRunnerStatus>("/api/v1/runner/stop", { method: "POST" }),

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

  paper: () => request<PaperSummary>("/api/v1/paper"),

  resetPaper: (initial_cash?: number) =>
    request<PaperSummary>("/api/v1/paper/reset", {
      method: "POST",
      body: JSON.stringify({ initial_cash }),
    }),

  storage: () =>
    request<{ driver: string; path: string; size_bytes?: number }>(
      "/api/v1/storage/status",
    ),
};
