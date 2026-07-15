/**
 * Risk / kill-switch endpoints.
 *
 * The kill switch is a global trip-wire that blocks all live trading
 * regardless of strategy mode. `toggleLiveTrading` is the global
 * master switch that gates the entire live-trading code path.
 *
 * Note: `risk` (the inner type used by `KillSwitchStatus`) is duplicated
 * here instead of imported from `engine.ts` to keep risk.ts free of
 * engine dependencies — engine is bigger and has more concerns.
 */

import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

export interface KillSwitchStatus {
  enabled: boolean;
  trading_enabled: boolean;
  risk: {
    trading_enabled: boolean;
    daily_pnl: number;
    current_drawdown: number;
    orders_last_minute: number;
    max_orders_per_minute: number;
  };
}

/** Single point in the risk history time series. */
export interface RiskSnapshot {
  timestamp: string;
  daily_pnl: number;
  current_drawdown: number;
  orders_last_minute: number;
  max_orders_per_minute: number;
  total_unrealized_pnl: number;
  kill_switch_enabled: boolean;
}

// ── Methods ──────────────────────────────────────────────────────

export const riskApi = {
  killSwitchStatus: () => request<KillSwitchStatus>("/api/v1/risk/kill-switch"),

  setKillSwitch: (enabled: boolean, reason: string) =>
    request<{ enabled: boolean; trading_enabled: boolean }>(
      "/api/v1/risk/kill-switch",
      { method: "POST", body: JSON.stringify({ enabled, reason }) },
    ),

  toggleLiveTrading: (enabled: boolean) =>
    request<{ live_trading_enabled: boolean }>(
      "/api/v1/settings/live-trading",
      { method: "POST", body: JSON.stringify({ enabled }) },
    ),

  /**
   * Risk history time series — last N minutes of snapshots written by
   * engine's `_risk_snapshot_loop` (every 30s). Used by RiskPage
   * sparklines on the "5 重保险" card.
   */
  riskHistory: (minutes = 30, limit = 200) => {
    const params = new URLSearchParams({
      minutes: String(minutes),
      limit: String(limit),
    });
    return request<{ snapshots: RiskSnapshot[]; minutes: number; limit: number; count: number }>(
      `/risk/history?${params.toString()}`,
    );
  },
};
