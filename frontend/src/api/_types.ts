/**
 * Shared type aliases used across the API client.
 *
 * Domain-specific types (Ticker, KLine, AppConfig, ...) live next to
 * the module that uses them. This file only holds the cross-domain
 * primitives (enum-like string unions).
 */

export type ExchangeName = "binance_usdm" | "bitget_usdt_futures" | "okx_swap";
export type Intent = "open_long" | "close_long" | "open_short" | "close_short";
export type Liquidity = "maker" | "taker";
export type MarginMode = "cross" | "isolated";
export type PositionSide = "net" | "long" | "short";
