"""CompositeObserver — Observer port adapter combining AlertSink + EventStore."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.core.sqlite_store import SQLiteStore
from app.engine.monitor import Monitor
from app.engine.pipeline_types import Observer, TradeEvent


class CompositeObserver:
    """Forwards TradeEvents to a Monitor (alerts) and SQLiteStore (audit).

    Translates the typed TradeEvent into the alert/audit payload shape each
    backend already understands. Single source of truth for what happens
    during pipeline execution.
    """

    def __init__(self, monitor: Monitor, store: SQLiteStore | None) -> None:
        self._monitor = monitor
        self._store = store

    def record(self, event: TradeEvent) -> None:
        from datetime import datetime

        from app.engine.monitor import Alert, AlertCategory, AlertLevel

        payload: Dict[str, Any] = dict(event.payload)

        if event.kind == "order_placed":
            self._monitor.push(
                Alert(
                    level=AlertLevel.INFO,
                    category=AlertCategory.ORDER,
                    title="Order placed",
                    message=f"{payload.get('side', '').upper()} {payload.get('quantity', '')} {payload.get('symbol', '')} @ {payload.get('price', '')}",
                    exchange=str(payload.get("exchange", "") or payload.get("symbol", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                )
            )
            if self._store is not None:
                self._store.append_event({
                    "category": "order",
                    "event_type": "live_order_submitted",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "order_id": str(payload.get("order_id", "")) or None,
                    "message": f"{payload.get('side', '').upper()} {payload.get('quantity', '')} {payload.get('symbol', '')} @ {payload.get('price', '')}",
                    "details": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        elif event.kind == "order_failed":
            self._monitor.push(
                Alert(
                    level=AlertLevel.ERROR,
                    category=AlertCategory.ORDER,
                    title="Order execution failed",
                    message=str(payload.get("error", "")),
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                )
            )
            if self._store is not None:
                self._store.append_event({
                    "category": "order",
                    "event_type": "live_order_failed",
                    "level": "error",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": str(payload.get("error", "")),
                    "details": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        elif event.kind == "risk_rejected":
            self._monitor.push(
                Alert(
                    level=AlertLevel.WARNING,
                    category=AlertCategory.RISK,
                    title="Order rejected by risk",
                    message=str(payload.get("reason", "")),
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                )
            )
            if self._store is not None:
                self._store.append_event({
                    "category": "risk",
                    "event_type": "order_rejected_by_risk",
                    "level": "warning",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": str(payload.get("reason", "")),
                    "details": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        elif event.kind == "gate_blocked":
            self._monitor.push(
                Alert(
                    level=AlertLevel.CRITICAL,
                    category=AlertCategory.RISK,
                    title="Trading gate blocked",
                    message="Kill switch engaged or live trading disabled",
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                )
            )
            if self._store is not None:
                self._store.append_event({
                    "category": "risk",
                    "event_type": "kill_switch_blocked",
                    "level": "critical",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": "Trading gate blocked the signal",
                    "details": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        elif event.kind == "signal_filtered":
            if self._store is not None:
                self._store.append_event({
                    "category": "signal",
                    "event_type": "signal_filtered",
                    "level": "info",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": f"Signal filtered by {payload.get('filter', 'unknown')}",
                    "details": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                })


__all__ = ["CompositeObserver"]