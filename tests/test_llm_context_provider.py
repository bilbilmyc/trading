"""Tests for the default LLM context provider.

The provider is a thin adapter over `RiskManager` + `SQLiteStore`, so the
tests are mostly about the *shape* of the data we hand to the prompt
template — that all the keys the prompt expects are present, even when
values are zero / missing.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.core.sqlite_store import SQLiteStore
from app.engine.llm_context import DefaultLLMContextProvider
from app.engine.risk_manager import RiskConfig, RiskManager


def _risk_manager(**overrides) -> RiskManager:
    cfg = RiskConfig()
    rm = RiskManager(cfg)
    for k, v in overrides.items():
        setattr(rm, k, v)
    return rm


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "h.sqlite3"))


# ── Risk context ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_context_maps_engine_keys_to_prompt_keys(tmp_path) -> None:
    """Provider must rename `current_drawdown` → `current_drawdown_pct`
    and `trading_enabled is False` → `kill_switch_enabled: True`,
    because the prompt template uses those names."""
    rm = _risk_manager()
    rm._daily_pnl = -75.0
    # current_drawdown = (peak - current) / peak = 0.09 → set peak=100, current=91
    rm._peak_value = 100.0
    rm._current_value = 91.0
    rm._order_timestamps = [1.0, 2.0]
    rm.config.max_orders_per_minute = 5

    provider = DefaultLLMContextProvider(risk_manager=rm, store=_store(tmp_path))
    ctx = await provider.get_risk_context()

    assert ctx is not None
    assert ctx["daily_pnl"] == -75.0
    assert abs(ctx["current_drawdown_pct"] - 0.09) < 0.001
    assert ctx["orders_last_minute"] == 2
    assert ctx["max_orders_per_minute"] == 5
    assert ctx["kill_switch_enabled"] is False


@pytest.mark.asyncio
async def test_risk_context_kill_switch_when_trading_disabled(tmp_path) -> None:
    rm = _risk_manager()
    rm.disable_trading()
    rm._daily_pnl = -200.0
    rm._peak_value = 100.0
    rm._current_value = 82.0  # 18% drawdown

    provider = DefaultLLMContextProvider(risk_manager=rm, store=_store(tmp_path))
    ctx = await provider.get_risk_context()

    assert ctx["kill_switch_enabled"] is True
    assert ctx["daily_pnl"] == -200.0
    assert abs(ctx["current_drawdown_pct"] - 0.18) < 0.001


@pytest.mark.asyncio
async def test_risk_context_returns_none_on_engine_error(tmp_path) -> None:
    class BrokenRisk:
        async def get_risk_status(self):
            raise RuntimeError("risk engine offline")

    provider = DefaultLLMContextProvider(risk_manager=BrokenRisk(), store=_store(tmp_path))
    assert await provider.get_risk_context() is None


# ── Trade history ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trade_history_empty_returns_none(tmp_path) -> None:
    rm = _risk_manager()
    provider = DefaultLLMContextProvider(risk_manager=rm, store=_store(tmp_path))
    assert await provider.get_trade_history("BTCUSDT") is None


@pytest.mark.asyncio
async def test_trade_history_basic_stats(tmp_path) -> None:
    store = _store(tmp_path)
    rows = [
        {
            "order_id": f"o{i}",
            "exchange": "binance_usdm",
            "strategy": "sma",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.1,
            "price": 50000.0,
            "fee": 0.0,
            "realized_pnl": pnl,
            "status": "filled",
            "timestamp": f"2026-01-{i+1:02d}",
        }
        for i, pnl in enumerate([10, 10, 10, 10, -5, -5])
    ]
    for r in rows:
        store.save_paper_order(r)

    rm = _risk_manager()
    provider = DefaultLLMContextProvider(risk_manager=rm, store=store)
    stats = await provider.get_trade_history("BTCUSDT")

    assert stats is not None
    assert stats["total_trades"] == 6
    assert stats["winning_trades"] == 4
    assert stats["losing_trades"] == 2
    assert abs(stats["win_rate"] - 4 / 6) < 0.01
    assert stats["avg_win"] == 10.0
    assert stats["avg_loss"] == -5.0


@pytest.mark.asyncio
async def test_trade_history_consecutive_streaks(tmp_path) -> None:
    store = _store(tmp_path)
    pnls_chronological = [10, 10, 10, -5, -5, -5, -5]
    for i, pnl in enumerate(pnls_chronological):
        store.save_paper_order({
            "order_id": f"o{i}",
            "exchange": "binance_usdm",
            "strategy": "sma",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.1,
            "price": 50000.0,
            "fee": 0.0,
            "realized_pnl": pnl,
            "status": "filled",
            "timestamp": f"2026-01-{i+1:02d}",
        })

    rm = _risk_manager()
    provider = DefaultLLMContextProvider(risk_manager=rm, store=store)
    stats = await provider.get_trade_history("BTCUSDT")

    assert stats["max_consecutive_wins"] == 3
    assert stats["max_consecutive_losses"] == 4


@pytest.mark.asyncio
async def test_trade_history_isolated_per_symbol(tmp_path) -> None:
    store = _store(tmp_path)
    for i, (sym, pnl) in enumerate([
        ("BTCUSDT", 10), ("ETHUSDT", -5), ("BTCUSDT", 10),
        ("ETHUSDT", -5), ("BTCUSDT", 10),
    ]):
        store.save_paper_order({
            "order_id": f"o{i}",
            "exchange": "binance_usdm",
            "strategy": "sma",
            "symbol": sym,
            "side": "buy",
            "quantity": 0.1,
            "price": 50000.0,
            "fee": 0.0,
            "realized_pnl": pnl,
            "status": "filled",
            "timestamp": f"2026-01-{i+1:02d}",
        })

    rm = _risk_manager()
    provider = DefaultLLMContextProvider(risk_manager=rm, store=store)
    btc = await provider.get_trade_history("BTCUSDT")
    eth = await provider.get_trade_history("ETHUSDT")

    assert btc["total_trades"] == 3
    assert btc["winning_trades"] == 3
    assert btc["losing_trades"] == 0
    assert eth["total_trades"] == 2
    assert eth["winning_trades"] == 0
    assert eth["losing_trades"] == 2
