"""Account state reconciliation guard for live-trading safety."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class AccountReconciliationGuard:
    """Block new exposure on exchanges with unresolved critical discrepancies.

    This guard is intentionally independent from the global kill switch.  A
    reconciliation block applies only to the affected venue and is used by both
    direct HTTP order routes and strategy-driven live pipelines.  Cancels and
    position-closing routes do not use it, so operators can always reduce risk.
    """

    def __init__(self) -> None:
        self._blocked: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _key(exchange: str) -> str:
        return exchange.lower()

    def observe(self, outcome: Any) -> bool:
        """Record a sync outcome and block its exchange when it is critical."""

        critical = [
            issue
            for issue in getattr(outcome, "issues", ())
            if str(issue.get("severity", "")).lower() == "critical"
        ]
        if not critical:
            return False
        exchange = self._key(str(outcome.exchange))
        now = datetime.now(UTC).isoformat()
        previous = self._blocked.get(exchange)
        self._blocked[exchange] = {
            "exchange": exchange,
            "blocked": True,
            "reason": "unresolved account/position reconciliation discrepancy",
            "critical_count": len(critical),
            "issues": critical,
            "blocked_at": previous.get("blocked_at", now) if previous else now,
            "last_synced_at": getattr(outcome, "completed_at", now),
        }
        # The durable issue ledger already records every sync pass.  Returning
        # only on the transition avoids emitting an alert/event every interval.
        return previous is None

    def restore(self, issues: list[dict[str, Any]]) -> None:
        """Restore unresolved blocks after a process restart."""

        grouped: dict[str, list[dict[str, Any]]] = {}
        for issue in issues:
            if str(issue.get("severity", "")).lower() != "critical":
                continue
            grouped.setdefault(self._key(str(issue["exchange"])), []).append(issue)
        for exchange, critical in grouped.items():
            self._blocked[exchange] = {
                "exchange": exchange,
                "blocked": True,
                "reason": "unresolved account/position reconciliation discrepancy",
                "critical_count": len(critical),
                "issues": critical,
                "blocked_at": min(str(issue.get("detected_at") or "") for issue in critical),
                "last_synced_at": None,
            }

    def is_blocked(self, exchange: str) -> bool:
        return self._key(exchange) in self._blocked

    def rejection_reason(self, exchange: str) -> str | None:
        state = self._blocked.get(self._key(exchange))
        return str(state["reason"]) if state else None

    def release(self, exchange: str) -> bool:
        """Release a block after an operator has explicitly reconciled it."""

        return self._blocked.pop(self._key(exchange), None) is not None

    def status(self, exchange: str | None = None) -> dict[str, Any]:
        if exchange:
            state = self._blocked.get(self._key(exchange))
            return {
                "exchange": self._key(exchange),
                "blocked": state is not None,
                "block": state,
            }
        blocks = list(self._blocked.values())
        return {
            "blocked": bool(blocks),
            "blocked_exchanges": blocks,
            "blocked_count": len(blocks),
        }


class AccountReconciliationFilter:
    """LiveOrderPipeline signal filter backed by :class:`AccountReconciliationGuard`."""

    name = "account_reconciliation"

    def __init__(self, guard: AccountReconciliationGuard) -> None:
        self._guard = guard

    async def check(self, _signal: Any, context: dict[str, Any]) -> bool:
        exchange = str(context.get("exchange") or "")
        return bool(exchange) and not self._guard.is_blocked(exchange)
