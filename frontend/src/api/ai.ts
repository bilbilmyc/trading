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

export interface LLMAnalysisResult {
  decision: string;
  confidence: number;
  reason: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  risk_level: string;
  risk_note: string;
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
