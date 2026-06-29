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
};
