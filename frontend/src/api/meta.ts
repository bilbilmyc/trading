/**
 * Meta / health / config endpoints.
 *
 * `health` is the only unauthenticated endpoint besides CORS preflight.
 * `config` and `exchanges` return environment metadata used by the
 * Settings page and the exchange selector.
 */

import { request } from "./_client";

// ── Types ─────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  env: string;
}

export interface AppConfig {
  app_name: string;
  app_env: string;
  default_exchange: string;
  default_symbol: string;
  live_trading_enabled: boolean;
  frontend_static_dir: string;
  persistence: { driver: string; path: string };
  exchanges: Record<string, { enabled: boolean; use_testnet: boolean; has_api_key: boolean }>;
  exchange_capabilities: Record<string, ExchangeCapabilities>;
  risk: Record<string, number>;
}

export interface ExchangeCapabilities {
  supports_hedge_mode: boolean;
  supports_post_only: boolean;
  requires_symbol_for_cancel_all: boolean;
  supports_public_fee_lookup: boolean;
  supports_private_fee_lookup: boolean;
}

/** Per-venue health snapshot returned by `/api/v1/health/venues`. */
export interface VenueHealth {
  enabled: boolean;
  use_testnet: boolean;
  credentials_present: boolean;
  public_api_ok: boolean;
  public_api_error: string | null;
  /** `null` when the venue has no API key configured (private probes skipped). */
  private_api_ok: boolean | null;
  private_api_error: string | null;
  clock_skew_ms: number | null;
  checked_at: string;
}

export interface VenueHealthResponse {
  venues: Record<string, VenueHealth>;
  timestamp: string;
}

// ── Methods ──────────────────────────────────────────────────────

export const metaApi = {
  health: () => request<HealthResponse>("/health"),

  config: () => request<AppConfig>("/api/v1/config"),

  exchanges: () => request<{ exchanges: string[]; enabled: string[] }>(
    "/api/v1/exchanges",
  ),

  venueHealth: () => request<VenueHealthResponse>("/api/v1/health/venues"),
};
