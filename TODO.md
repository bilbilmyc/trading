# Quant Trading System TODO

This project should evolve as a professional quant trading system, not just a
manual trading console. Use this TODO as the next-development entry point.

## Product Direction

- Primary venue: Binance USD-M Futures.
- Secondary venue: Bitget USDT Futures.
- Backup venue: OKX Swap.
- Default posture: paper/signal first, live trading explicitly gated.
- Architecture target: research -> backtest -> paper -> live, with shared data,
  shared risk checks, and auditable execution records.

## Institutional-Grade Reference Model

High-end quant stacks usually separate these responsibilities:

- Market data layer: normalized ticks, candles, funding, open interest, fees,
  instrument metadata, and data-quality checks.
- Research layer: feature engineering, factor studies, notebooks/scripts,
  experiment metadata, and reproducible datasets.
- Backtest layer: event-driven simulation, realistic fees/slippage/funding,
  position accounting, parameter sweeps, and walk-forward validation.
- Portfolio layer: capital allocation, exposure netting, leverage budgets,
  portfolio-level drawdown and correlation controls.
- Risk layer: pre-trade checks, post-trade checks, kill switch, max loss,
  stale data detection, exchange degradation handling.
- Execution layer: OMS/EMS separation, order lifecycle, retries, idempotency,
  partial fills, reduce-only correctness, and reconciliation.
- Operations layer: metrics, alerts, logs, dashboards, secrets, deployment,
  runbooks, and incident review.

## Phase 1: Make Current System Safer

- [ ] Add a global kill switch API and UI control.
- [x] Persist all submitted live orders, rejected orders, and cancel requests.
- [x] Add idempotent `client_order_id` generation for every live order.
- [x] Add explicit order preview before any live order: notional, leverage,
  margin mode, reduce-only, estimated fee, liquidation-risk note.
- [ ] Split public market errors from private account/order errors in the API
  response shape, not only in the frontend.
- [ ] Add exchange capability flags: supports hedge mode, supports post-only,
  requires symbol for cancel-all, supports public fee lookup.
- [ ] Add health checks for each enabled venue: public API, private API,
  clock skew, credentials present, and rate-limit status.
- [x] Add tests for live-trading guard: order/cancel/leverage must reject when
  `ENABLE_LIVE_TRADING=false`.

## Phase 2: Data Foundation

- [ ] Create SQLite tables for normalized candles, tickers, trades, funding
  rates, instrument snapshots, and data-quality events.
- [ ] Add a market data ingestor service for Binance first, then Bitget, then
  OKX.
- [ ] Add data deduplication and gap detection for candles.
- [ ] Add a `/api/v1/data/quality` endpoint and frontend status panel.
- [ ] Add candle cache so strategy evaluation does not repeatedly hit exchange
  APIs for the same recent data.
- [ ] Add historical backfill command: `uv run python main.py backfill`.

## Phase 3: Backtesting And Research

- [ ] Build an event-driven backtest engine using the same `Signal` and risk
  interfaces as paper/live.
- [ ] Model maker/taker fees, funding, slippage, spread, and latency.
- [ ] Add performance metrics: CAGR, Sharpe, Sortino, max drawdown, win rate,
  profit factor, turnover, exposure, average holding time.
- [ ] Add parameter sweep for SMA and LLM-filter thresholds.
- [ ] Add walk-forward validation and train/test split utilities.
- [ ] Persist backtest runs, parameters, metrics, and equity curves in SQLite.
- [ ] Add frontend backtest view: run selector, equity curve, drawdown, trades.

## Phase 4: Portfolio And Risk

- [ ] Move from per-order risk only to portfolio-level risk.
- [ ] Add max gross exposure, max net exposure, max leverage, and max symbol
  concentration.
- [ ] Add exchange-level capital allocation: Binance primary, Bitget auxiliary,
  OKX backup.
- [ ] Add daily/weekly loss lockout with reset rules.
- [ ] Add stale-market-data rejection before order creation.
- [ ] Add correlation-aware exposure limits for major assets.
- [x] Add risk event persistence and a frontend risk-event timeline.

## Phase 5: Execution Quality

- [ ] Introduce an OMS layer for order intent, order state, fills, and cancels.
- [ ] Introduce an EMS layer for exchange-specific execution adapters.
- [ ] Track partial fills and average fill price accurately.
- [ ] Add order reconciliation loop comparing local state with exchange state.
- [ ] Add retry policy with idempotency and safe terminal states.
- [ ] Add reduce-only validation for close-long/close-short on all venues.
- [ ] Add execution analytics: slippage, fill latency, reject rate, cancel rate.

## Phase 6: Strategy System

- [ ] Add a strategy registry with versioned strategy configs.
- [ ] Persist strategy lifecycle events: created, enabled, disabled, mode
  changed, deleted.
- [ ] Add strategy sandboxing: max symbols, max notional, max orders per
  strategy.
- [ ] Add multi-symbol strategy support.
- [ ] Add funding-rate strategy inputs.
- [ ] Add LLM strategy guardrails: deterministic JSON schema validation,
  confidence thresholds, max order amount, and reason logging.
- [ ] Add strategy dry-run reports before enabling paper/live mode.

## Phase 7: Frontend Console

- [ ] Add venue priority labels: Primary Binance, Secondary Bitget, Backup OKX.
- [ ] Add health strip per venue with public/private status.
- [ ] Add storage status page for SQLite tables and row counts.
- [ ] Add risk dashboard with kill switch, loss lockout, and exposure.
- [ ] Add backtest dashboard.
- [ ] Add execution dashboard: open orders, fills, rejects, cancels, slippage.
- [ ] Add settings screen for exchange enablement and default symbol.
- [ ] Keep desktop console dense and operational; avoid marketing-style pages.

## Phase 8: Testing

- [ ] Add API tests with FastAPI `TestClient` for config, storage, strategies,
  live-trading guard, and exchange error handling.
- [ ] Add exchange adapter unit tests for Binance, Bitget, and OKX payloads.
- [ ] Add paper-trading accounting tests for open, scale-in, partial close,
  flip long-to-short, fees, realized/unrealized PnL.
- [ ] Add risk-manager tests for order value, rate limit, drawdown, daily loss.
- [ ] Add backtest engine tests once implemented.
- [ ] Add frontend smoke tests for default Binance, Bitget switch, and live
  disabled order button.

## Phase 9: Operations

- [ ] Add structured JSON logs for order/risk/exchange events.
- [ ] Add metrics endpoint for Prometheus-compatible scraping.
- [ ] Add alert channels: console, webhook, email/Telegram later.
- [ ] Add deployment profile for local, paper, and live.
- [ ] Add secret handling guide; never commit real API keys.
- [ ] Add runbooks: start paper mode, recover from exchange outage, stop live
  trading, reconcile orders.

## Current Known Gaps

- SQLite is suitable for local/single-node development, but not enough for
  multi-process live trading without stricter locking and migration discipline.
- Bitget private endpoints are mapped but need credentialed testnet/demo
  verification before live use.
- Binance private fee/open-order calls fail without API keys; UI handles this
  but API should expose clearer public/private error categories.
- WebSocket support is incomplete for Bitget futures.
- Backtesting is not implemented yet; current paper trading is not a substitute
  for research-grade simulation.
- Order state is not yet a full OMS.

## Next Best Task

Add a global kill switch API and UI control. It should block strategy live
execution and manual order endpoints, persist kill-switch events, and be visible
in the frontend risk panel.
