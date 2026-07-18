/**
 * AI / LLM market analysis endpoints.
 *
 * `aiAnalyze` is the one-shot analysis endpoint — it returns an
 * `LLMAnalysisResult` but does NOT submit any orders. Strategy-level
 * LLM usage goes through `api/strategies.ts` (LLM strategy CRUD).
 */

import { request } from "./_client";

export type LLMErrorKind =
  | "api_key_missing"
  | "http_error"
  | "timeout"
  | "parse_error"
  | "rate_limited"
  | "network"
  | "safety_rejected"
  | "circuit_open";

// ── Types ─────────────────────────────────────────────────────────

export interface LLMTechnicalIndicators {
  count?: number;
  data_quality?: "sufficient" | "limited" | "unavailable";
  trend_bias?: "bullish" | "bearish" | "neutral";
  sma_5?: number | null;
  sma_20?: number | null;
  rsi_14?: number | null;
  momentum_5_pct?: number | null;
  momentum_20_pct?: number | null;
  atr_14?: number | null;
  atr_pct?: number | null;
  volume_ratio?: number | null;
  support_20?: number | null;
  resistance_20?: number | null;
}

export interface LLMAnalysisResult {
  decision: "buy" | "sell" | "hold" | string;
  confidence: number;
  reason: string;
  suggested_action?: string | null;
  suggested_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  risk_level: "low" | "medium" | "high" | string;
  risk_note: string;
  trend?: "bullish" | "bearish" | "neutral";
  volatility?: "low" | "medium" | "high";
  summary?: string;
  key_support?: number | null;
  key_resistance?: number | null;
  entry_zone?: string;
  position_pct?: number;
  bullish_factors?: string[];
  bearish_factors?: string[];
  invalidation_condition?: string;
  risk_reward_ratio?: number | null;
  technical_indicators?: LLMTechnicalIndicators | null;
  analyzed_symbol?: string;
  analyzed_interval?: string;
  model?: string;
  analysis_time?: string;
  candle_count?: number;
  cache_hit?: boolean;
  error_kind?: LLMErrorKind | null;
}

export interface LLMModelInsight {
  provider: string;
  model: string;
  calls: number;
  successful_calls: number;
  failed_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
}

export interface LLMInsights {
  window_minutes: number;
  generated_at: string;
  event_limit: number;
  calls_total: number;
  successful_calls: number;
  failed_calls: number;
  safety_rejections: number;
  success_rate: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  decisions: Record<"buy" | "sell" | "hold", number>;
  failures: Record<string, number>;
  models: LLMModelInsight[];
}

// ── Methods ──────────────────────────────────────────────────────

export const aiApi = {
  aiAnalyze: (payload: { exchange: string; symbol: string; interval: string; limit: number }) =>
    request<LLMAnalysisResult>("/api/v1/ai/analyze", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  llmInsights: (params: { minutes?: number; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.minutes !== undefined) query.set("minutes", String(params.minutes));
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const queryString = query.toString();
    const suffix = queryString ? `?${queryString}` : "";
    return request<LLMInsights>(`/api/v1/ai/insights${suffix}`);
  },
};
