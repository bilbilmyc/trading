/**
 * Portfolio metrics, equity curves, trade history, and strategy leaderboard.
 *
 * Endpoints under `/api/v1/portfolio/*` and `/api/v1/trade-history`.
 * Trade history returns paper-trading orders (not real exchange trades);
 * portfolio metrics come from the in-process position manager.
 */

import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

// Loosely-typed records on purpose: the response shape comes straight
// from the SQLite trade_history view, which has a dynamic schema. The
// pages cast to their own narrower types after fetch.
export interface TradeRecord {
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
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
}

export interface LeaderboardEntry {
  rank: number;
  strategy: string;
  score: number;
}

// ── Methods ──────────────────────────────────────────────────────

export const portfolioApi = {
  portfolioEquityCurves: () =>
    request<{ curves: Record<string, EquityPoint[]> }>(
      "/api/v1/portfolio/equity-curves",
    ),

  tradeHistory: (params: { limit?: number; strategy?: string; exchange?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.limit) search.set("limit", String(params.limit));
    if (params.strategy) search.set("strategy", params.strategy);
    if (params.exchange) search.set("exchange", params.exchange);
    const qs = search.toString();
    return request<{ trades: TradeRecord[] }>(
      `/api/v1/trade-history${qs ? `?${qs}` : ""}`,
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
    request<{ strategies: LeaderboardEntry[] }>(
      "/api/v1/strategies/leaderboard",
    ),
};
