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

export interface ExecutionIntent {
  client_order_id: string;
  exchange: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  price?: number | null;
  status: "submitting" | "submitted" | "unknown" | "pending" | "partially_filled";
  exchange_order_id?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReconciliationIssue {
  id: number;
  exchange: string;
  issue_key: string;
  kind: string;
  severity: "critical" | "warning";
  resource?: string | null;
  local?: Record<string, unknown> | null;
  exchange_state?: Record<string, unknown> | null;
  status: "open" | "resolved";
  detected_at: string;
  updated_at: string;
  resolved_at?: string | null;
  resolution_note?: string | null;
}

export interface ReconciliationGuardStatus {
  blocked: boolean;
  blocked_count?: number;
  blocked_exchanges?: Array<{
    exchange: string;
    reason: string;
    critical_count: number;
    blocked_at: string;
  }>;
  exchange?: string;
  block?: {
    exchange: string;
    reason: string;
    critical_count: number;
    blocked_at: string;
  } | null;
}

export interface ReconciliationStatus {
  guard: ReconciliationGuardStatus;
  summary: { open_count: number; critical_count: number; warning_count: number };
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

  pendingExecutions: (exchange?: string) =>
    request<{ intents: ExecutionIntent[]; count: number }>(
      `/api/v1/executions/pending${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`,
    ),

  reconciliationStatus: (exchange?: string) =>
    request<ReconciliationStatus>(
      `/api/v1/reconciliation/status${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`,
    ),

  reconciliationIssues: (exchange?: string, status: "open" | "resolved" = "open") =>
    request<{ issues: ReconciliationIssue[]; count: number }>(
      `/api/v1/reconciliation/issues?status=${status}${exchange ? `&exchange=${encodeURIComponent(exchange)}` : ""}`,
    ),

  recoverReconciliation: (exchange: string, note: string) =>
    request<{ exchange: string; released: boolean; resolved_issues: number; guard: ReconciliationGuardStatus }>(
      `/api/v1/reconciliation/${encodeURIComponent(exchange)}/recover`,
      { method: "POST", body: JSON.stringify({ note }) },
    ),

  closePosition: (payload: { exchange: string; symbol: string; exit_quantity?: number; position_size_pct?: number }) =>
    request<{ closed_quantity: number; order: Record<string, unknown> }>(
      "/api/v1/positions/close",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  closePaperPosition: (payload: { exchange: string; symbol: string; exit_quantity?: number; position_size_pct?: number }) =>
    request<{ closed_quantity: number; order: Record<string, unknown> }>(
      "/api/v1/paper/positions/close",
      { method: "POST", body: JSON.stringify(payload) },
    ),
};
