"""Focused integration tests for engine-owned correlation market data."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from app.core.sqlite_store import SQLiteStore
from app.engine.trader import TradingEngine


def test_engine_correlation_does_not_fallback_to_another_exchange(tmp_path) -> None:
    async def scenario() -> None:
        engine = TradingEngine(store=SQLiteStore(str(tmp_path / "trader.sqlite3")))
        candidate_exchange = AsyncMock()
        candidate_exchange.name = "candidate"
        candidate_exchange.get_klines.return_value = [
            {"open_time": datetime(2026, 1, 1), "close": 100.0},
            {"open_time": datetime(2026, 1, 1, 1), "close": 101.0},
            {"open_time": datetime(2026, 1, 1, 2), "close": 102.0},
        ]
        engine.add_exchange("candidate", candidate_exchange)
        await engine.position_manager.update_position("held_exchange", "BTCUSDT", 1.0, 100.0, "buy")

        snapshot = await engine._position_correlation_snapshot("ETHUSDT", "candidate", "1h", 8, 2)

        assert snapshot.correlations == {}
        assert snapshot.unavailable_symbols == ("BTCUSDT",)
        candidate_exchange.get_klines.assert_awaited_once_with("ETHUSDT", interval="1h", limit=8)

    asyncio.run(scenario())
