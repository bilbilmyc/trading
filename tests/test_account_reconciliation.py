"""Regression coverage for exchange-authoritative account reconciliation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.result import Err
from app.core.sqlite_store import SQLiteStore
from app.engine.account_reconciliation import (
    AccountReconciliationFilter,
    AccountReconciliationGuard,
)
from app.engine.live_order_pipeline import LiveOrderPipeline
from app.engine.position_manager import PositionManager
from app.engine.position_sync import PositionSync
from app.exchanges.contract_base import ContractExchangeBase
from app.strategies.base import Signal, SignalAction


def _contract_exchange(
    *,
    balances: dict[str, object] | None = None,
    positions: list[dict[str, object]] | None = None,
) -> AsyncMock:
    exchange = AsyncMock(spec=ContractExchangeBase)
    exchange.get_account_balance = AsyncMock(return_value=balances or {})
    exchange.get_positions = AsyncMock(return_value=positions or [])
    return exchange


@pytest.mark.asyncio
async def test_quantity_difference_adopts_exchange_state_and_blocks_new_exposure() -> None:
    manager = PositionManager()
    await manager.update_position("test_contract", "BTCUSDT", 0.1, 50_000, "buy")
    sync = PositionSync(manager)
    exchange = _contract_exchange(
        balances={"USDT": {"total": 1_000, "available": 800}},
        positions=[
            {
                "symbol": "BTCUSDT",
                "quantity": "0.2",
                "avg_price": "50100",
                "current_price": "50200",
            }
        ],
    )

    updated = await sync.sync(exchange, "test_contract")

    outcome = sync.last_outcome("TEST_CONTRACT")
    assert updated == 2
    assert outcome is not None
    assert outcome.position_sync_ok is True
    assert any(issue["kind"] == "position_quantity_mismatch" for issue in outcome.issues)
    position = await manager.get_position("test_contract", "BTCUSDT")
    assert position is not None
    assert position.quantity == 0.2

    guard = AccountReconciliationGuard()
    assert guard.observe(outcome) is True
    assert guard.observe(outcome) is False
    assert guard.is_blocked("TEST_CONTRACT") is True
    assert (
        await AccountReconciliationFilter(guard).check(object(), {"exchange": "test_contract"})
        is False
    )
    assert guard.release("test_contract") is True
    assert (
        await AccountReconciliationFilter(guard).check(object(), {"exchange": "test_contract"})
        is True
    )


@pytest.mark.asyncio
async def test_unknown_exchange_position_and_missing_local_position_are_critical() -> None:
    manager = PositionManager()
    await manager.update_position("test_contract", "ETHUSDT", 0.3, 3_000, "buy")
    sync = PositionSync(manager)

    await sync.sync(
        _contract_exchange(
            positions=[
                {
                    "symbol": "BTCUSDT",
                    "quantity": "0.1",
                    "avg_price": "50000",
                    "current_price": "50050",
                }
            ]
        ),
        "test_contract",
    )

    outcome = sync.last_outcome("test_contract")
    assert outcome is not None
    assert {issue["kind"] for issue in outcome.issues} == {
        "unexpected_position",
        "missing_position",
    }
    eth = await manager.get_position("test_contract", "ETHUSDT")
    btc = await manager.get_position("test_contract", "BTCUSDT")
    assert eth is not None and eth.quantity == 0
    assert btc is not None and btc.quantity == 0.1


@pytest.mark.asyncio
async def test_balance_difference_is_recorded_as_warning_without_hard_block() -> None:
    manager = PositionManager()
    await manager.update_balance("spot", "USDT", total=100, available=90)
    sync = PositionSync(manager)
    exchange = AsyncMock()
    exchange.get_account_balance = AsyncMock(
        return_value={"USDT": {"total": 110, "available": 100}}
    )

    await sync.sync(exchange, "spot")

    outcome = sync.last_outcome("spot")
    assert outcome is not None
    assert [issue["severity"] for issue in outcome.issues] == ["warning"]
    guard = AccountReconciliationGuard()
    assert guard.observe(outcome) is False
    assert guard.is_blocked("spot") is False


@pytest.mark.asyncio
async def test_pipeline_safety_filter_blocks_strategy_orders_before_risk_or_placement() -> None:
    class OpenGuard:
        async def is_open(self) -> bool:
            return True

    class Exchange:
        name = "test_contract"

    class Observer:
        def __init__(self) -> None:
            self.events = []

        def record(self, event) -> None:
            self.events.append(event)

    guard = AccountReconciliationGuard()
    guard.restore(
        [
            {
                "exchange": "test_contract",
                "severity": "critical",
                "kind": "unexpected_position",
                "detected_at": "2026-07-17T00:00:00+00:00",
            }
        ]
    )
    observer = Observer()
    pipeline = LiveOrderPipeline(
        exchange=Exchange(),
        trading_guard=OpenGuard(),
        risk_gate=object(),
        order_tracker=object(),
        position_recorder=object(),
        observer=observer,
        semaphore=asyncio.Semaphore(1),
        safety_filter=AccountReconciliationFilter(guard),
    )
    signal = Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.9,
        quantity=0.001,
    )

    result = await pipeline.execute(signal)

    assert isinstance(result, Err)
    assert result.unwrap_err().stage == "filter"
    assert result.unwrap_err().reason == "rejected by account_reconciliation"
    assert observer.events[0].kind == "signal_filtered"
    assert observer.events[0].payload["filter"] == "account_reconciliation"


def test_store_persists_issues_and_restores_a_reconciliation_block(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "reconciliation.sqlite3"))
    issue = {
        "issue_key": "position_quantity_mismatch:BTCUSDT",
        "kind": "position_quantity_mismatch",
        "resource": "BTCUSDT",
        "severity": "critical",
        "local": {"quantity": 0.1},
        "exchange": {"quantity": 0.2},
    }
    outcome = {
        "exchange": "binance_usdm",
        "balances": [],
        "positions": [],
        "issues": [issue],
        "balance_sync_ok": True,
        "position_sync_ok": True,
        "errors": [],
        "completed_at": "2026-07-17T00:00:00+00:00",
    }

    store.append_account_snapshot(outcome)
    store.upsert_reconciliation_issues("BINANCE_USDM", [issue])

    persisted = store.reconciliation_issues()
    assert len(persisted) == 1
    assert persisted[0]["exchange"] == "binance_usdm"
    assert persisted[0]["exchange_state"] == {"quantity": 0.2}
    snapshot = store._conn.execute(
        "SELECT balances_json, positions_json, errors_json FROM account_snapshots"
    ).fetchone()
    assert tuple(snapshot) == ("[]", "[]", "[]")

    restarted_guard = AccountReconciliationGuard()
    restarted_guard.restore(persisted)
    assert restarted_guard.is_blocked("binance_usdm") is True
    assert store.resolve_reconciliation_issues("binance_usdm", "operator confirmed") == 1
    assert store.reconciliation_issues() == []
    assert (
        store.reconciliation_issues(status="resolved")[0]["resolution_note"] == "operator confirmed"
    )
    store.close()
