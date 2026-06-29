/**
 * Order placement / cancel / preview / close endpoints.
 *
 * All write operations on real positions go through this module. The
 * backend enforces the global `ENABLE_LIVE_TRADING` gate; the frontend
 * just shows the error if a write is rejected.
 */

import type { ExchangeName, Intent, Liquidity, MarginMode, PositionSide } from "./_types";
import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

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

// ── Methods ──────────────────────────────────────────────────────

export const ordersApi = {
  placeContractOrder: (payload: ContractOrderPayload) =>
    request<{ order: Record<string, unknown>; order_id?: string }>(
      "/api/v1/contracts/order",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  previewContractOrder: (payload: ContractOrderPayload) =>
    request<ContractOrderPreview>("/api/v1/contracts/order/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  closePosition: (payload: { exchange: string; symbol: string; exit_quantity?: number }) =>
    request<{ closed_quantity: number; order: Record<string, unknown> }>(
      "/api/v1/positions/close",
      { method: "POST", body: JSON.stringify(payload) },
    ),
};
