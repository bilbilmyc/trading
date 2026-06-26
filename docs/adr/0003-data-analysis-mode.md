# ADR-0003: Data Analysis Mode — decouple data sources from trading exchanges

**Status:** Accepted · 2026-06-26

Decouple public market data access from trading-exchange registration. Make the app usable without configuring any exchange API keys; LLM remains optional; trading is opt-in via `ENABLE_LIVE_TRADING=true` + per-exchange API keys. Frontend defaults to a Data Analysis landing page.

## Problem

The current architecture couples data access to trading capability:

- `build_engine()` auto-registers every `ExchangeFactory.list_supported_exchanges()` instance, requiring exchange-specific credentials at startup.
- API routes (`/api/v1/ticker/{exchange}/{symbol}`, `/klines`, `/trades`, `/contracts`) require the exchange to be registered with `engine.add_exchange()` — unregistered exchanges return 404.
- Frontend exchange selectors hardcode the three built-in options (Binance, OKX, Bitget).
- The user's stated focus is **data analysis queries**, not exchange-specific trading. Forcing them to pick an exchange up front to do data analysis is friction.

LLM keys are already handled gracefully (`Failed(kind=API_KEY_MISSING)` in v2) but the frontend doesn't surface this — it just shows a generic error.

## Solution

### Backend

1. **Two-layer architecture**: introduce a `DataSource` Protocol separate from `TradingExchange`.
   - `DataSource` — public market data only (ticker / klines / trades / contracts). No auth required. `ExchangeBase` already implements this shape, so existing adapters remain valid `DataSource` instances.
   - `TradingExchange` — extends `DataSource` with private + order operations. Requires per-exchange API keys + global `ENABLE_LIVE_TRADING=true`.

2. **AppState separates registries**: `state.data_sources: dict[name, DataSource]` and `state.trading_exchanges: dict[name, ExchangeBase]`. Both default empty.

3. **Startup behavior**:
   - For each entry in `ExchangeFactory.list_supported_exchanges()` where the per-exchange settings say `enabled=true`, register as a **data source** (always — public endpoints work without keys).
   - Only register as a **trading exchange** if `settings.enable_live_trading` AND `api_key != ""`.

4. **Routes**:
   - Public market routes (`/ticker`, `/klines`, `/trades`, `/contracts`, `/cost-estimate`, `/fee-rate`) resolve through `data_sources`. 404 only if not registered.
   - Trading routes (`/order`, `/contracts/order`, `/cancel`, `/leverage`) require `state.trading_exchanges`. Return 503 "trading not configured" if no trading exchange exists.
   - `/api/v1/ai/analyze` passes through `LLMAnalysisResult.error_kind` in the response so the frontend can detect "not configured" specifically.

### Frontend

1. **Default landing page changes from `/trade` to `/data`**. `/trade` becomes a sub-page only available when at least one trading exchange is configured.
2. **New `/data` page**: data-source management. Lists registered data sources, lets user add custom data sources by URL/name. Shows the symbol browser (klines + ticker) without committing to a specific exchange.
3. **`Trade` page guard**: if `state.trading_exchanges` is empty, render a "configure a trading exchange" prompt instead of the order form.
4. **`/ai/analyze` button**: detect `error_kind === "api_key_missing"` and render a "未配置 LLM API Key — 在 Settings 配置" message instead of the generic error. Disable the button.

## User Stories

1. As a data analyst, I want to launch the app with zero configuration, so that I can immediately query market data.
2. As a data analyst, I want public market endpoints (ticker, klines, trades, contracts) to work without any exchange API keys, so that I can analyze data without opening trading accounts.
3. As a data analyst, I want to register a custom data source by URL, so that I can pull data from sources beyond the three built-in exchanges.
4. As a data analyst, I want the default landing page to focus on data queries, so that I'm not pushed toward trading by default.
5. As a trader, I want to opt into trading by configuring API keys + setting `ENABLE_LIVE_TRADING=true`, so that the app exposes trading routes only when I'm ready.
6. As a trader, I want the Trade page to disappear or be replaced with a configuration prompt when no trading exchange is configured, so that I don't accidentally hit non-functional routes.
7. As an AI strategy user, I want to use the app fully (without LLM features) when I haven't configured an LLM API key, so that strategies and data analysis still work.
8. As an AI strategy user, I want a clear "未配置 LLM" message when I try to use AI analysis, so that I know exactly what to configure.
9. As a backend developer, I want the engine to be testable without any network or external dependencies, so that CI runs reliably.
10. As a backend developer, I want `build_engine()` to be deterministic about what it registers, so that tests don't depend on environment variables.

## Implementation Decisions

- **`DataSource` Protocol** lives in `app/data_sources/base.py`. Three methods: `name`, `get_ticker`, `get_klines`, `get_recent_trades`, `list_contracts`. `ExchangeBase` already conforms — no inheritance change needed.
- **`TradingExchange` Protocol** lives in `app/exchanges/base.py` (extends DataSource with private methods). Implementation is the existing `ExchangeBase` class.
- **`AppState`** holds `data_sources` and `trading_exchanges` as separate dicts. Initialization logic in `AppState.__init__` is the single source of truth for which exchanges get registered and in what mode.
- **`build_engine()` in main.py** becomes a thin convenience wrapper that calls `AppState` initialization. It will continue to register an SMA strategy, but the exchange registration moves to `AppState`.
- **Routing**: a small `_resolve_data_source(name)` helper in `server.py` replaces the current direct dict lookup. Trading routes get a separate `_resolve_trading_exchange(name)` that 503s when missing.
- **Settings**: `Settings.exchange(name)` already returns per-exchange config; we use that to drive registration. No new config keys required — `api_key == ""` means "data source only".
- **`/api/v1/ai/analyze` response shape**: include `error_kind` (string or null) alongside the existing `decision/confidence/reason/cached` fields. Frontend reads it.
- **Frontend data sources page**: `/data` lists registered data sources with name + status; has an "Add custom source" form (name + base URL). Custom sources are stored in `localStorage` for now (no backend persistence yet — keeps scope tight).
- **Frontend trade page guard**: read `data_sources` count from `EngineContext`. If 0 and no trading exchange, show configuration prompt.
- **No backward-compatibility shim**: this is a breaking change for the old `EXCHANGE_OPTIONS` enum and the `/trade` default. Documented in CHANGELOG / ADR.

## Testing Decisions

- **Public behavior only**. Tests assert on `AppState.data_sources`, `AppState.trading_exchanges`, response bodies, and observable side effects — not internal scheduler state.
- **Each TDD vertical slice proves one behavior end-to-end** through `AppState` (highest seam).
- **Prior art**: existing `test_kill_switch.py`, `test_live_trading_guard.py` already use `TestClient(create_app(Settings(...)))` and assert on `app.state` and response bodies. New tests follow the same pattern.
- **TickerCache pipeline tests** show how to test cross-component wiring through the public seam; we'll extend the pattern.
- **Frontend**: keep using `TestClient` for the API surface; the React changes are mostly component reshuffling (move TradePage guard + add DataSourcesPage) and don't need their own unit tests.

## Out of Scope

- Replacing existing exchange adapters with CCXT (big change, not needed for this PRD).
- Persisting user-added custom data sources to SQLite (localStorage only for now).
- Backfilling historical data (kline gap-filling, multi-exchange aggregation).
- SSE push for AI analysis results (still request/response).
- Auth / multi-user — single-user local app stays the model.
- Migrating existing open PRs or branches — none expected.

## Further Notes

- This change rolls out as 6 vertical slices, each with its own commit. Slice order is dependency-driven:
  1. `build_engine()` skips trading exchanges when no keys.
  2. `DataSource` Protocol defined; existing `ExchangeBase` confirmed to conform.
  3. Public market routes use `data_sources` registry; unregistered sources → 404 still.
  4. `/api/v1/ai/analyze` exposes `error_kind` in response.
  5. Frontend `/data` page with data-source browser.
  6. Frontend Trade page guard + AI analyze error surface.
- The ADR file replaces any prior `enable_live_trading` semantics — that flag now governs trading exchanges only, not data sources.
- `TradingEngine` itself stays unchanged; it just receives fewer (or zero) exchanges at startup.