# Trading

The trading engine context: a quantitative trading system that ingests market data, runs strategies, applies risk gates, and routes orders to spot or contract exchanges. Single live path per signal; paper trading is a deliberately separate parallel path.

## Language

### Pipeline

**LiveOrderPipeline**:
The module that orchestrates a single live trade end to end — from a passed `Signal` to a placed exchange order with full risk, tracking, and audit discipline.
_Avoid_: "execution engine", "trading service"

**TradingGuard**:
The port that answers "may we trade right now?" — kill switch and live-trading enable flag.
_Avoid_: "kill switch module", "trading state"

**RiskGate**:
The port that evaluates an order against position, value, drawdown, rate, and daily-loss limits. Returns a typed `RiskDecision`.
_Avoid_: "risk manager" (now reserved for the implementation of this port), "risk check"

**RiskDecision**:
The discriminated result of a `RiskGate.check` — one of `Allowed`, `PositionTooLarge`, `RateLimited`, `DailyLossExceeded`, `DrawdownExceeded`.
_Avoid_: free-form boolean + reason tuple

**SignalFilter**:
A protocol for async functions that may veto a `Signal` after strategy generation but before placement (e.g. LLM second-pass confirmation).
_Avoid_: "signal callback", "pre-trade hook"

### Tracking

**OrderTracker**:
The port that records a placed `Order` locally for later reconciliation against the exchange.
_Avoid_: "order sync module" (now reserved for the implementation of this port)

**PositionRecorder**:
The port that updates the local position state when an order is placed.
_Avoid_: "position manager" (now reserved for the implementation of this port)

**Observer**:
The port that emits `TradeEvent`s for both human-facing alerts and persistent audit records. Composed of one `AlertSink` and one `EventStore`.
_Avoid_: "monitor", "logger"

**TradeEvent**:
An event observed during pipeline execution — one of `SignalFiltered`, `GateBlocked`, `RiskRejected`, `OrderPlaced`, `OrderFailed`.
_Avoid_: "audit log entry", "alert"

### Result

**TradeReceipt**:
The successful result of `LiveOrderPipeline.execute` — order id, filled quantity, average fill price, side, exchange, and the originating `Signal`.
_Avoid_: "order response", "execution result"

**TradeError**:
The failed result of `LiveOrderPipeline.execute` — carries a `stage` discriminator (which step vetoed or failed) and a reason.

**Result**:
A typed Ok / Err wrapper used at module boundaries where callers must handle both outcomes.

### Existing core (referenced, not redefined)

**TradingEngine**:
The top-level orchestrator. Owns the strategy registry, exchange registry, and the background reconciliation loops. After the `LiveOrderPipeline` extraction, `TradingEngine` delegates per-signal execution to the pipeline instead of running `_execute_signal` inline.

**RiskManager**:
The current risk module. Will become an adapter of the `RiskGate` port; its kill-switch and trading-enabled concerns move to `TradingGuard`.

**OrderSync**:
The current module that pulls exchange open-orders and reconciles them locally. Will become an adapter of the `OrderTracker` port.

**PositionManager**:
The current in-memory positions/balances store. Will become an adapter of the `PositionRecorder` port.