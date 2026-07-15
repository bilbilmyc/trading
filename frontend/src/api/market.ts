/**
 * Public market data endpoints — no auth required, all exchanges.
 *
 * Methods are exported via `marketApi` and merged into the top-level
 * `api` object in `api.ts`. Types defined here are the canonical shapes
 * the rest of the codebase uses for market data.
 */

import type { ExchangeName, Liquidity } from "./_types";
import { request } from "./_client";

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

export interface FeeRate {
  exchange: string;
  symbol: string;
  maker: number;
  taker: number;
  timestamp: string;
  raw: Record<string, unknown>;
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

export const marketApi = {
  ticker: (exchange: ExchangeName, symbol: string) =>
    request<Ticker>(`/ticker/${exchange}/${symbol}`),

  klines: (exchange: ExchangeName, symbol: string, interval = "1h", limit = 80) => {
    const params = new URLSearchParams({ interval, limit: String(limit) });
    return request<Candle[]>(
      `/klines/${exchange}/${encodeURIComponent(symbol)}?${params.toString()}`,
    );
  },

  recentTrades: (exchange: ExchangeName, symbol: string, limit = 8) => {
    const params = new URLSearchParams({ limit: String(limit) });
    return request<RecentTrade[]>(
      `/trades/${exchange}/${encodeURIComponent(symbol)}?${params.toString()}`,
    );
  },

  contracts: (exchange: ExchangeName, search = "", limit = 200) =>
    request<{ contracts: ContractMarket[]; total: number }>(
      `/contracts/${exchange}?search=${encodeURIComponent(search)}&limit=${limit}`,
    ),

  openOrders: (exchange: ExchangeName, symbol: string) => {
    const params = new URLSearchParams({ symbol });
    return request<OpenOrder[]>(
      `/orders/${exchange}/open?${params.toString()}`,
    );
  },

  feeRate: (exchange: ExchangeName, symbol: string) =>
    request<FeeRate>(`/contracts/${exchange}/${symbol}/fee-rate`),

  costEstimate: (
    exchange: ExchangeName,
    symbol: string,
    quantity: number,
    price: number,
    liquidity: "maker" | "taker" | string = "taker",
  ) => {
    const params = new URLSearchParams({
      quantity: String(quantity),
      price: String(price),
      liquidity,
    });
    return request<CostEstimate>(
      `/contracts/${exchange}/${symbol}/cost-estimate?${params.toString()}`,
    );
  },

  prices: () => request<Record<string, number>>("/prices"),

  /**
   * 24h change snapshot for a small watchlist. Cached server-side for
   * 20s; missing data renders as `null` so the UI can show "—".
   */
  topMovers: (opts?: { exchange?: string; symbols?: string[] }) => {
    const params = new URLSearchParams();
    if (opts?.exchange) params.set("exchange", opts.exchange);
    if (opts?.symbols?.length) params.set("symbols", opts.symbols.join(","));
    const qs = params.toString();
    return request<{
      exchange: string;
      items: Array<{
        symbol: string;
        price: number | null;
        change_pct_24h: number | null;
        change_24h?: number | null;
        high_24h?: number | null;
        low_24h?: number | null;
        error?: string;
      }>;
      error?: string;
      timestamp: string;
    }>(`/market/top-movers${qs ? `?${qs}` : ""}`);
  },
};
