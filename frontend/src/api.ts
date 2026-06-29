/**
 * Top-level HTTP client for the trading backend — thin re-export shim.
 *
 * `import { api } from "./api"` is the single surface used by pages
 * and contexts. Internally the `api` object is composed of per-domain
 * partials (`marketApi`, `ordersApi`, `engineApi`, ...) defined in
 * sibling modules under `./api/`.
 *
 * To add a new endpoint, decide which domain it belongs to and update
 * the corresponding file:
 *   - market data (ticker, klines, ...)    → `api/market.ts`
 *   - order placement / cancel              → `api/orders.ts`
 *   - engine / runner / paper / storage     → `api/engine.ts`
 *   - strategy CRUD + signals              → `api/strategies.ts`
 *   - portfolio metrics / trade history    → `api/portfolio.ts`
 *   - AI / LLM analysis                    → `api/ai.ts`
 *   - kill switch + risk settings          → `api/risk.ts`
 *   - meta (health, config, exchanges)     → `api/meta.ts`
 *   - shared types (enum aliases)           → `api/_types.ts`
 *   - shared fetch client                  → `api/_client.ts`
 *
 * Re-exports preserve the original `import { Ticker } from "./api"`
 * surface so no page or context needs to change.
 */

import { API_BASE, request } from "./api/_client";
import { marketApi } from "./api/market";
import { ordersApi } from "./api/orders";
import { engineApi } from "./api/engine";
import { strategiesApi } from "./api/strategies";
import { portfolioApi } from "./api/portfolio";
import { aiApi } from "./api/ai";
import { riskApi } from "./api/risk";
import { metaApi, type HealthResponse, type AppConfig, type ExchangeCapabilities } from "./api/meta";

export type {
  ExchangeName, Intent, Liquidity, MarginMode, PositionSide,
} from "./api/_types";
export type {
  Ticker, ContractMarket, RecentTrade, Candle, OpenOrder, FeeRate, CostEstimate,
} from "./api/market";
export type { ContractOrderPayload, ContractOrderPreview } from "./api/orders";
export type { EngineStatus } from "./api/engine";
export type {
  StrategyInfo, PaperSummary, PaperPosition, PaperOrder, StrategySignal,
  AuditEvent, CreateSMAStrategyPayload, SignalRunnerStatus,
} from "./api/strategies";
export type { TradeRecord, EquityPoint, LeaderboardEntry } from "./api/portfolio";
export type { LLMAnalysisResult } from "./api/ai";
export type { KillSwitchStatus } from "./api/risk";
export type { HealthResponse, AppConfig, ExchangeCapabilities } from "./api/meta";

export const api = {
  baseUrl: API_BASE,
  ...marketApi,
  ...ordersApi,
  ...engineApi,
  ...strategiesApi,
  ...portfolioApi,
  ...aiApi,
  ...riskApi,
  ...metaApi,
};

// Pages that build custom URLs (e.g. SSE) call `api.request`.
(api as unknown as { request: typeof request }).request = request;
