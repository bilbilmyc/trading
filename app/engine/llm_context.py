"""Default LLM context provider — adapts engine state into the LLM prompt.

The LLM prompt (P1-4) expects two optional context blocks: risk metrics
and recent trade history. This adapter produces them from the live
`RiskManager` and `SQLiteStore` so the strategy sees an up-to-date picture
on every signal call.

Design choice: a thin adapter (this file) rather than reaching into the
engine from inside `LLMStrategy`. The strategy stays a pure object that
accepts any `LLMContextProvider`; the wiring lives in the API layer.
"""

from __future__ import annotations

from typing import Any

from app.core.sqlite_store import SQLiteStore
from app.engine.risk_manager import RiskManager


class DefaultLLMContextProvider:
    """Adapts `RiskManager` + `SQLiteStore` to the LLMContextProvider protocol.

    Both dependencies are passed by reference — the provider reads the
    current state on every call, so changes (kill switch toggle, new
    fills) are visible to the next LLM signal request without rebuilding
    the provider.
    """

    # How many recent paper orders to scan when computing win rate etc.
    # 200 matches the trade-history page default; small enough to be fast.
    _TRADE_HISTORY_LOOKBACK = 200

    def __init__(
        self,
        risk_manager: RiskManager,
        store: SQLiteStore,
    ) -> None:
        self._risk = risk_manager
        self._store = store

    # ── LLMContextProvider surface ────────────────────────────────

    async def get_risk_context(self) -> dict[str, Any] | None:
        """Live risk metrics. Returns None if the engine has no risk state yet."""
        try:
            status = await self._risk.get_risk_status()
        except Exception:
            return None
        if not isinstance(status, dict):
            return None
        # Map engine keys → prompt keys. The prompt template expects:
        #   daily_pnl, current_drawdown_pct, kill_switch_enabled,
        #   orders_last_minute, max_orders_per_minute
        return {
            "daily_pnl": float(status.get("daily_pnl", 0.0) or 0.0),
            "current_drawdown_pct": float(
                status.get("current_drawdown", 0.0) or 0.0
            ),
            "kill_switch_enabled": bool(
                status.get("trading_enabled") is False
            ),
            "orders_last_minute": int(status.get("orders_last_minute", 0) or 0),
            "max_orders_per_minute": int(
                status.get("max_orders_per_minute", 0) or 0
            ),
        }

    async def get_trade_history(self, symbol: str) -> dict[str, Any] | None:
        """Recent trade performance for the given symbol, computed from
        the SQLite `paper_orders` table.

        Returns None if the store has no orders or symbol filter rejects
        everything (avoids the LLM seeing a misleading "0 of 0" result
        for a brand-new symbol).
        """
        try:
            all_orders: list[dict[str, Any]] = self._store.recent_paper_orders(
                limit=self._TRADE_HISTORY_LOOKBACK,
            )
        except Exception:
            return None
        # The store's `recent_paper_orders` filters by strategy/exchange, not
        # by symbol. Apply the symbol filter in Python — at most _LOOKBACK
        # rows in memory, so this stays cheap.
        orders = [o for o in all_orders if o.get("symbol") == symbol]
        if not orders:
            return None

        pnls = [float(o.get("realized_pnl") or 0.0) for o in orders]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total = len(pnls)

        # Longest consecutive runs (oldest first so the streak is well-defined)
        ordered_chronological = list(reversed(orders))
        max_w, max_l, cur_w, cur_l = 0, 0, 0, 0
        for o in ordered_chronological:
            p = float(o.get("realized_pnl") or 0.0)
            if p > 0:
                cur_w += 1
                cur_l = 0
            elif p < 0:
                cur_l += 1
                cur_w = 0
            else:
                # Break-even fill doesn't extend a streak in either direction
                cur_w = 0
                cur_l = 0
            max_w = max(max_w, cur_w)
            max_l = max(max_l, cur_l)

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": (len(wins) / total) if total else 0.0,
            "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
            "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
            "max_consecutive_wins": max_w,
            "max_consecutive_losses": max_l,
        }

    async def get_backtest_performance(self, symbol: str) -> dict[str, Any] | None:
        """Return the newest matching immutable backtest summary for the symbol."""
        try:
            runs = self._store.recent_backtest_experiments(limit=50)
        except Exception:
            return None
        for run in runs:
            request = run.get("request") if isinstance(run.get("request"), dict) else {}
            if str(request.get("symbol") or "").upper() != symbol.upper():
                continue
            result = run.get("result") if isinstance(run.get("result"), dict) else {}
            return {
                "experiment_id": run.get("id"),
                "strategy_name": run.get("strategy_name"),
                "strategy_version": run.get("strategy_version"),
                "created_at": run.get("created_at"),
                "result": result,
            }
        return None

    async def get_recent_ai_decisions(self, symbol: str) -> list[dict[str, Any]] | None:
        """Return a compact, restart-safe AI decision history for prompt context."""
        try:
            events = self._store.recent_events(
                category="llm", event_type="llm_decision", limit=100
            )
        except Exception:
            return None
        decisions: list[dict[str, Any]] = []
        for event in reversed(events):
            if event.get("symbol") != symbol:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            decisions.append(
                {
                    "timestamp": event.get("timestamp"),
                    "decision": details.get("decision"),
                    "confidence": details.get("confidence"),
                    "regime": details.get("output_summary", {}).get("regime")
                    if isinstance(details.get("output_summary"), dict)
                    else None,
                    "outcome_return_pct": details.get("outcome_return_pct"),
                    "failed": details.get("failed"),
                }
            )
            if len(decisions) >= 10:
                break
        return decisions or None
