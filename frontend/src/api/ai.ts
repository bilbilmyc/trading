/**
 * AI / LLM market analysis endpoints.
 *
 * `aiAnalyze` is the one-shot analysis endpoint — it returns an
 * `LLMAnalysisResult` but does NOT submit any orders. Strategy-level
 * LLM usage goes through `api/strategies.ts` (LLM strategy CRUD).
 */

import { request } from "./_client";

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
  error_kind?: string | null;
}

// ── Methods ──────────────────────────────────────────────────────

export const aiApi = {
  aiAnalyze: (payload: { exchange: string; symbol: string; interval: string; limit: number }) =>
    request<LLMAnalysisResult>("/api/v1/ai/analyze", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
