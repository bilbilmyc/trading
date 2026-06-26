"""Tracer bullet — LiveOrderPipeline.execute happy path.

The pipeline orchestrates one Signal end-to-end through six ports:
trading guard → signal filters → risk gate → exchange → tracker → recorder → observer.

This test exercises every port via in-memory fakes; the assertions are on
observable behaviour only (result value + recorded side effects), so the
implementation can change without breaking the test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from app.core.result import Err, Ok
from app.engine.live_order_pipeline import LiveOrderPipeline
from app.engine.pipeline_types import (
    OrderTracker,
    Observer,
    PositionRecorder,
    RiskDecision,
    RiskGate,
    SignalFilter,
    TradeEvent,
    TradeReceipt,
    TradingGuard,
)
from app.strategies.base import Signal, SignalAction


# ── fakes ────────────────────────────────────────────────────────────


@dataclass
class _RecordedEvent:
    kind: str
    payload: Dict[str, Any]


class FakeObserver:
    def __init__(self) -> None:
        self.events: List[_RecordedEvent] = []

    def record(self, event: TradeEvent) -> None:
        self.events.append(_RecordedEvent(kind=event.kind, payload=event.payload))


class FakeTracker:
    def __init__(self) -> None:
        self.tracked: List[Any] = []

    def track(self, order: Any) -> None:
        self.tracked.append(order)


class FakePositionRecorder:
    def __init__(self) -> None:
        self.records: List[TradeReceipt] = []

    async def record(self, receipt: TradeReceipt) -> None:
        self.records.append(receipt)


class AlwaysOpenGuard:
    async def is_open(self) -> bool:
        return True


class AlwaysClosedGuard:
    async def is_open(self) -> bool:
        return False


class AlwaysAllowedRiskGate:
    async def check(self, signal: Signal, price: float) -> RiskDecision:
        return RiskDecision(allowed=True, reason="ok", stop_loss=None, take_profit=None)


class FakeExchange:
    """Just enough surface for LiveOrderPipeline.execute."""

    def __init__(self, ticker_price: float = 100.0, place_result: Dict[str, Any] | None = None) -> None:
        self._ticker_price = ticker_price
        self._place_result = place_result or {"order_id": "fake-order-1"}
        self.placed: List[Dict[str, Any]] = []

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        return {"last_price": self._ticker_price}

    async def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        self.placed.append(kwargs)
        return dict(self._place_result)


# ── helpers ──────────────────────────────────────────────────────────


def _buy_signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.9,
        quantity=0.001,
        price=None,  # forces ticker fetch in pipeline
        order_type="market",
        stop_loss=None,
        take_profit=None,
    )


def _pipeline(
    *,
    exchange: FakeExchange | None = None,
    guard: TradingGuard | None = None,
    risk_gate: RiskGate | None = None,
    tracker: OrderTracker | None = None,
    recorder: PositionRecorder | None = None,
    observer: Observer | None = None,
    filters=(),
) -> tuple[LiveOrderPipeline, FakeObserver, FakeTracker, FakePositionRecorder, FakeExchange]:
    ex = exchange or FakeExchange()
    tr = tracker or FakeTracker()
    rc = recorder or FakePositionRecorder()
    ob = observer or FakeObserver()
    pipe = LiveOrderPipeline(
        exchange=ex,
        trading_guard=guard or AlwaysOpenGuard(),
        risk_gate=risk_gate or AlwaysAllowedRiskGate(),
        order_tracker=tr,
        position_recorder=rc,
        observer=ob,
        semaphore=asyncio.Semaphore(5),
        signal_filters=filters,
    )
    return pipe, ob, tr, rc, ex


# ── tracer bullet ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_places_order_and_emits_single_placed_event() -> None:
    pipe, observer, tracker, recorder, exchange = _pipeline()

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Ok)
    receipt = result.unwrap()
    assert receipt.order_id == "fake-order-1"
    assert receipt.symbol == "BTCUSDT"
    assert receipt.filled_quantity > 0

    # exactly one placed event recorded
    assert len(observer.events) == 1
    assert observer.events[0].kind == "order_placed"

    # tracker + recorder each saw the receipt
    assert len(tracker.tracked) == 1
    assert len(recorder.records) == 1
    assert recorder.records[0].order_id == "fake-order-1"

    # exchange got exactly one place_order call
    assert len(exchange.placed) == 1
    assert exchange.placed[0]["symbol"] == "BTCUSDT"
    assert exchange.placed[0]["side"] == "buy"


@pytest.mark.asyncio
async def test_guard_closed_short_circuits_before_risk_or_place() -> None:
    pipe, observer, tracker, recorder, exchange = _pipeline(guard=AlwaysClosedGuard())

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Err)
    err = result.unwrap_err()
    assert err.stage == "guard"
    assert "disabled" in err.reason

    # observer saw the gate_blocked event and nothing else
    assert len(observer.events) == 1
    assert observer.events[0].kind == "gate_blocked"

    # downstream ports NOT called
    assert tracker.tracked == []
    assert recorder.records == []
    assert exchange.placed == []


class RejectingFilter:
    """Always-veto filter; class name surfaces in the rejection event."""

    async def check(self, signal, context):
        return False


class AllowingFilter:
    async def check(self, signal, context):
        return True


@pytest.mark.asyncio
async def test_filter_veto_short_circuits_before_risk_or_place() -> None:
    pipe, observer, tracker, recorder, exchange = _pipeline(
        filters=[RejectingFilter()]
    )

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Err)
    err = result.unwrap_err()
    assert err.stage == "filter"

    assert len(observer.events) == 1
    assert observer.events[0].kind == "signal_filtered"
    assert observer.events[0].payload["filter"] == "RejectingFilter"

    assert tracker.tracked == []
    assert recorder.records == []
    assert exchange.placed == []


@pytest.mark.asyncio
async def test_multiple_filters_all_must_pass() -> None:
    """A passing filter after a rejecting one still results in Err — chain stops at first veto."""

    class CountingAllow:
        def __init__(self) -> None:
            self.calls = 0

        async def check(self, signal, context):
            self.calls += 1
            return True

    allow = CountingAllow()
    pipe, observer, _, _, exchange = _pipeline(
        filters=[RejectingFilter(), allow, allow]
    )

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Err)
    assert result.unwrap_err().stage == "filter"
    # First filter vetoed; subsequent ones must not have been consulted.
    assert allow.calls == 0
    assert exchange.placed == []


class RejectingRiskGate:
    async def check(self, signal, price):
        return RiskDecision(allowed=False, reason="max position value exceeded")


@pytest.mark.asyncio
async def test_risk_rejection_blocks_before_place() -> None:
    pipe, observer, tracker, recorder, exchange = _pipeline(
        risk_gate=RejectingRiskGate()
    )

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Err)
    err = result.unwrap_err()
    assert err.stage == "risk"
    assert "max position" in err.reason

    assert len(observer.events) == 1
    assert observer.events[0].kind == "risk_rejected"

    assert tracker.tracked == []
    assert recorder.records == []
    assert exchange.placed == []


class FailingExchange:
    """Exchange whose place_order always raises."""

    async def get_ticker(self, symbol):
        return {"last_price": 100.0}

    async def place_order(self, **kwargs):
        raise RuntimeError("exchange down")


@pytest.mark.asyncio
async def test_place_failure_emits_order_failed_and_does_not_record() -> None:
    pipe, observer, tracker, recorder, exchange = _pipeline(exchange=FailingExchange())

    result = await pipe.execute(_buy_signal())

    assert isinstance(result, Err)
    err = result.unwrap_err()
    assert err.stage == "place"
    assert "exchange down" in err.reason

    assert len(observer.events) == 1
    assert observer.events[0].kind == "order_failed"

    assert tracker.tracked == []
    assert recorder.records == []