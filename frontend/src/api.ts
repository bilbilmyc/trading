export type ExchangeName = "okx_swap" | "binance_usdm";
export type Intent = "open_long" | "close_long" | "open_short" | "close_short";
export type Liquidity = "maker" | "taker";
export type MarginMode = "cross" | "isolated";
export type PositionSide = "net" | "long" | "short";

export interface HealthResponse {
  status: string;
  env: string;
}

export interface EngineStatus {
  running: boolean;
  exchanges: string[];
  strategies: string[];
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
}

function resolveApiBase() {
  if (import.meta.env.VITE_API_BASE_URL) return import.meta.env.VITE_API_BASE_URL;
  if (window.location.port === "5173") return "http://127.0.0.1:8000";
  return window.location.origin;
}

const API_BASE = resolveApiBase();

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
    const message = payload?.detail ?? response.statusText;
    throw new Error(Array.isArray(message) ? JSON.stringify(message) : message);
  }
  return payload as T;
}

export const api = {
  baseUrl: API_BASE,

  health: () => request<HealthResponse>("/health"),

  exchanges: () => request<{ exchanges: string[] }>("/api/v1/exchanges"),

  engineStatus: () => request<EngineStatus>("/api/v1/engine/status"),

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

  placeContractOrder: (payload: ContractOrderPayload) =>
    request<Record<string, unknown>>("/api/v1/contracts/order", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
