"""CompositeObserver — Observer port adapter combining AlertSink + EventStore.

Batched store writes: monitor.push fires immediately (real-time alerts),
but store.append_events accumulates in a buffer and flushes either when
the buffer reaches `buffer_max` or `flush_interval` seconds elapse, whichever
comes first. Cuts fsync overhead when many events fire in a tight window.

Translates the typed TradeEvent into the alert/audit payload shape each
backend already understands.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.sqlite_store import SQLiteStore
from app.engine.monitor import Alert, AlertCategory, AlertLevel, Monitor
from app.engine.pipeline_types import Observer, TradeEvent


class CompositeObserver(Observer):
    def __init__(
        self,
        monitor: Monitor,
        store: Optional[SQLiteStore],
        buffer_max: int = 10,
        flush_interval: float = 0.5,
    ) -> None:
        self._monitor = monitor
        self._store = store
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_max = max(1, buffer_max)
        self._flush_interval = max(0.01, flush_interval)
        self._flush_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._stopped = False
        self._alert_payloads: Dict[str, Dict[str, Any]] = {}

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        if self._flush_task is not None:
            return
        self._stopped = False
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self._flush()

    async def _flush_loop(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
        except asyncio.CancelledError:
            return

    async def _flush(self) -> None:
        async with self._flush_lock:
            if not self._buffer or self._store is None:
                return
            events = self._buffer
            self._buffer = []
            self._store.append_events(events)

    # ── Public API ─────────────────────────────────────────────

    def record(self, event: TradeEvent) -> None:
        """Translate TradeEvent into alert + audit payload and dispatch.

        Alert goes to the monitor immediately. Audit row is buffered
        for batched flush.
        """
        payload: Dict[str, Any] = dict(event.payload)
        now = datetime.utcnow().isoformat()
        alert, audit = self._translate(event.kind, payload, now)

        if alert is not None:
            self._monitor.push(alert)

        if audit is not None and self._store is not None:
            self._buffer.append(audit)
            if len(self._buffer) >= self._buffer_max:
                # Schedule a flush; do not block the caller.
                asyncio.create_task(self._flush())

    # ── Translation ────────────────────────────────────────────

    @staticmethod
    def _translate(kind: str, payload: Dict[str, Any], now: str) -> tuple:
        if kind == "order_placed":
            return (
                Alert(
                    level=AlertLevel.INFO,
                    category=AlertCategory.ORDER,
                    title="Order placed",
                    message=f"{payload.get('side', '').upper()} {payload.get('quantity', '')} {payload.get('symbol', '')} @ {payload.get('price', '')}",
                    exchange=str(payload.get("exchange", "") or payload.get("symbol", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                ),
                {
                    "category": "order",
                    "event_type": "live_order_submitted",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "order_id": str(payload.get("order_id", "")) or None,
                    "message": f"{payload.get('side', '').upper()} {payload.get('quantity', '')} {payload.get('symbol', '')} @ {payload.get('price', '')}",
                    "details": payload,
                    "timestamp": now,
                },
            )
        if kind == "order_failed":
            return (
                Alert(
                    level=AlertLevel.ERROR,
                    category=AlertCategory.ORDER,
                    title="Order execution failed",
                    message=str(payload.get("error", "")),
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                ),
                {
                    "category": "order",
                    "event_type": "live_order_failed",
                    "level": "error",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": str(payload.get("error", "")),
                    "details": payload,
                    "timestamp": now,
                },
            )
        if kind == "risk_rejected":
            return (
                Alert(
                    level=AlertLevel.WARNING,
                    category=AlertCategory.RISK,
                    title="Order rejected by risk",
                    message=str(payload.get("reason", "")),
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                ),
                {
                    "category": "risk",
                    "event_type": "order_rejected_by_risk",
                    "level": "warning",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": str(payload.get("reason", "")),
                    "details": payload,
                    "timestamp": now,
                },
            )
        if kind == "gate_blocked":
            return (
                Alert(
                    level=AlertLevel.CRITICAL,
                    category=AlertCategory.RISK,
                    title="Trading gate blocked",
                    message="Kill switch engaged or live trading disabled",
                    exchange=str(payload.get("exchange", "")),
                    symbol=str(payload.get("symbol", "")),
                    details=payload,
                ),
                {
                    "category": "risk",
                    "event_type": "kill_switch_blocked",
                    "level": "critical",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": "Trading gate blocked the signal",
                    "details": payload,
                    "timestamp": now,
                },
            )
        if kind == "signal_filtered":
            return (
                None,
                {
                    "category": "signal",
                    "event_type": "signal_filtered",
                    "level": "info",
                    "exchange": str(payload.get("exchange", "")),
                    "symbol": str(payload.get("symbol", "")),
                    "message": f"Signal filtered by {payload.get('filter', 'unknown')}",
                    "details": payload,
                    "timestamp": now,
                },
            )
        return (None, None)


__all__ = ["CompositeObserver"]