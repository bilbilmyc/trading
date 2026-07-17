/**
 * Deterministic SMA backtest endpoint.
 *
 * The response deliberately exposes execution assumptions and every completed
 * trade so the UI can present results as an estimate rather than a promise.
 */

import type { Candle } from "./market";
import { request } from "./_client";

export interface BacktestPayload {
  klines: Candle[];
  short_window?: number;
  long_window?: number;
  initial_capital?: number;
  position_size_pct?: number;
  fee_rate?: number;
  slippage_rate?: number;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
}

export interface BacktestTrade {
  entry_index: number;
  exit_index: number;
  entry_time: string | number | null;
  exit_time: string | number | null;
  quantity: number;
  entry_price: number;
  exit_price: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  exit_reason: "signal" | "stop_loss" | "take_profit" | "end_of_data" | string;
}

export interface BacktestResult {
  initial_capital: number;
  final_equity: number;
  total_pnl: number;
  total_fees: number;
  gross_pnl: number;
  total_return_pct: number;
  trades: number;
  win_rate: number;
  max_drawdown: number;
  profit_factor: number | null;
  equity_curve: number[];
  trade_history: BacktestTrade[];
  klines_used: Candle[];
}


export interface WalkForwardCandidate {
  short_window: number;
  long_window: number;
}

export interface WalkForwardPayload extends BacktestPayload {
  train_size: number;
  test_size: number;
  step_size?: number;
  candidate_parameters?: WalkForwardCandidate[];
}

export interface WalkForwardFold {
  fold: number;
  train_start: number;
  train_end: number;
  test_start: number;
  test_end: number;
  selected_parameters: WalkForwardCandidate;
  train_return_pct: number;
  train_max_drawdown: number;
  out_of_sample: Omit<BacktestResult, "equity_curve" | "trade_history" | "klines_used">;
}

export interface WalkForwardResult {
  folds: WalkForwardFold[];
  initial_capital: number;
  final_equity: number;
  total_pnl: number;
  total_return_pct: number;
  trades: number;
  win_rate: number;
  max_drawdown: number;
  total_fees: number;
  profitable_fold_ratio: number;
  return_stddev_pct: number;
}

export const backtestApi = {
  run: (payload: BacktestPayload) =>
    request<BacktestResult>("/backtest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  runWalkForward: (strategyName: string, payload: WalkForwardPayload) =>
    request<{ id: number; strategy: string; strategy_version: number; kind: string; result: WalkForwardResult }>(
      `/api/v1/strategies/${encodeURIComponent(strategyName)}/backtests/walk-forward`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
};
