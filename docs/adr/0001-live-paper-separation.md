# ADR-0001: Keep live and paper trading paths separate

**Status:** Accepted · 2026-06-26

`TradingEngine` has two parallel code paths for executing a Signal: `_execute_signal` (live, full discipline) and `_maybe_apply_paper_signal` (paper, ~20 LOC, skips filters / risk / alerts / events). The 2026-06-26 architecture review proposed merging them behind a unified `BasePipeline` with `LiveOrderPipeline` and `PaperOrderPipeline` subclasses; that proposal was rejected three times during the design walk. We keep the two paths separate.

The paper path is a deliberate fast iteration loop — strategy developers use it to dry-run SL/TP variants and stress-test sizing without enforcement. The two paths also don't share an "executor" shape: paper reaches into `exchange.get_ticker` for prices but never calls `exchange.place_order`; live does the opposite. Merging would force at least one side to lose capability.

## Considered Options

- **Unify behind a single pipeline (rejected)** — both sides become subclasses of `BasePipeline`. Loses paper's intentional laxity; the port grows a second optional method.
- **Keep both paths separate (chosen)** — `LiveOrderPipeline` extraction targets the live path only; paper path stays as-is. Discipline asymmetry is a documented property, not a defect.

## Consequences

- Future architecture reviews will re-propose unifying. This ADR is the place to send them; reopen only if a concrete reason appears (e.g., a paper bug that an audit event would have caught).
- Paper's missing audit trail is now a known property rather than an oversight. Address it inside `_maybe_apply_paper_signal` only if paper becomes compliance-critical.
- `LiveOrderPipeline` extraction is bounded; the paper path is out of scope and untouched.

## Related

- `CONTEXT.md` — vocabulary established during this work (`LiveOrderPipeline`, `TradingGuard`, `RiskGate`, `Observer`, etc.).