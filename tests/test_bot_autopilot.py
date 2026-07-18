"""Tests for the deterministic unattended Bot multi-timeframe analysis."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.bot.autopilot import analyze_multi_timeframe, extract_closes


def _candles(start: float, hourly_return: float, count: int = 25):
    price = start
    candles = []
    for _ in range(count):
        candles.append({"close": price})
        price *= 1 + hourly_return
    return candles


def test_extract_closes_ignores_invalid_values():
    assert extract_closes([{"close": "100"}, {"close": 0}, {}, {"close": "bad"}]) == [100.0]


def test_multi_timeframe_buy_requires_all_windows_to_align():
    decision = analyze_multi_timeframe(
        _candles(100.0, 0.003),
        min_return_pct=0.002,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )

    assert decision.action == "buy"
    assert decision.reason == "all_timeframes_aligned"
    assert decision.confidence > 0.5
    assert [signal.action for signal in decision.signals] == ["buy", "buy", "buy"]


def test_multi_timeframe_sell_requires_all_windows_to_align():
    decision = analyze_multi_timeframe(_candles(100.0, -0.003), min_return_pct=0.002)

    assert decision.action == "sell"
    assert [signal.action for signal in decision.signals] == ["sell", "sell", "sell"]


def test_multi_timeframe_signal_key_is_stable_across_analysis_retries():
    first = analyze_multi_timeframe(_candles(100.0, 0.003), min_return_pct=0.002)
    second = analyze_multi_timeframe(_candles(100.0, 0.003), min_return_pct=0.002)

    assert first.decision_id != second.decision_id
    assert first.signal_key == second.signal_key


def test_multi_timeframe_mixed_or_weak_signal_observes():
    candles = _candles(100.0, 0.003)
    # Recent one-hour downturn conflicts with 5h / 24h uptrend.
    candles[-1]["close"] = candles[-2]["close"] * 0.996

    decision = analyze_multi_timeframe(candles, min_return_pct=0.002)

    assert decision.action == "observe"
    assert decision.reason == "timeframes_disagree"


def test_multi_timeframe_insufficient_data_never_trades():
    decision = analyze_multi_timeframe(_candles(100.0, 0.01, count=8))

    assert decision.action == "observe"
    assert decision.reason == "insufficient_closed_candles_for_24h"
    assert decision.price is not None


def test_multi_timeframe_rejects_invalid_threshold():
    with pytest.raises(ValueError, match="min_return_pct"):
        analyze_multi_timeframe(_candles(100.0, 0.01), min_return_pct=0)


def test_autopilot_analysis_endpoint_records_an_auditable_observe_or_signal(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.server import create_app
    from config import Settings

    class _Source:
        async def get_klines(self, symbol, interval, limit):
            assert symbol == "BTCUSDT"
            assert interval == "1h"
            assert limit == 26
            return _candles(100.0, 0.003, count=26)

    settings = Settings(
        sqlite_path=str(tmp_path / "autopilot.sqlite3"),
        frontend_static_dir=str(tmp_path / "static"),
        bot_autopilot_enabled=True,
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.trading.data_sources["binance_usdm"] = _Source()
        response = client.get(
            "/api/v1/bot/autopilot/analysis",
            params={"exchange": "binance_usdm", "symbol": "BTCUSDT"},
        )
        events = client.app.state.trading.store.recent_events(
            category="bot", event_type="autopilot_analysis", limit=5
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "buy"
    assert payload["live_order_allowed"] is False
    assert events[-1]["details"]["decision"]["decision_id"] == payload["decision_id"]


def test_autopilot_analysis_endpoint_is_disabled_by_default(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.server import create_app
    from config import Settings

    settings = Settings(
        sqlite_path=str(tmp_path / "autopilot-disabled.sqlite3"),
        frontend_static_dir=str(tmp_path / "static"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/bot/autopilot/analysis",
            params={"exchange": "binance_usdm", "symbol": "BTCUSDT"},
        )

    assert response.status_code == 409


def test_autopilot_budget_reservation_is_atomic_and_idempotent(tmp_path):
    from app.core.sqlite_store import SQLiteStore

    store = SQLiteStore(str(tmp_path / "budget.sqlite3"))
    try:
        assert store.reserve_bot_autopilot_notional(
            decision_id="bot-decision-1",
            budget_date="2026-07-18",
            notional=25.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:00:00+00:00",
        ) == (True, 0.0, False)
        # The same decision represents a retry, not another budget draw.
        assert store.reserve_bot_autopilot_notional(
            decision_id="bot-decision-1",
            budget_date="2026-07-18",
            notional=25.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:01:00+00:00",
        ) == (True, 0.0, True)
        assert store.reserve_bot_autopilot_notional(
            decision_id="bot-decision-2",
            budget_date="2026-07-18",
            notional=80.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:02:00+00:00",
        ) == (False, 25.0, False)
    finally:
        store.close()


def test_autopilot_order_requires_fresh_signal_and_respects_budgeted_execution(tmp_path):
    """A consensus decision can submit exactly one capped order through every guard."""
    from fastapi.testclient import TestClient

    from app.api.server import create_app
    from config import Settings

    class _TradingSource:
        def __init__(self):
            self.placed = []
            self.ticker_calls = 0

        async def get_klines(self, symbol, interval, limit):
            assert (symbol, interval, limit) == ("BTCUSDT", "1h", 26)
            return _candles(100.0, 0.003, count=26)

        async def get_ticker(self, symbol):
            assert symbol == "BTCUSDT"
            self.ticker_calls += 1
            return {"last_price": 100.0}

        async def place_order(self, **kwargs):
            self.placed.append(kwargs)
            return {"order_id": "bot-order-1", "status": "filled"}

        async def close(self):
            return None

    settings = Settings(
        sqlite_path=str(tmp_path / "autopilot-order.sqlite3"),
        frontend_static_dir=str(tmp_path / "static"),
        enable_live_trading=True,
        bot_autopilot_enabled=True,
        bot_autopilot_live_order_enabled=True,
        bot_autopilot_max_order_notional=25.0,
        bot_autopilot_max_daily_notional=100.0,
    )
    source = _TradingSource()
    with TestClient(create_app(settings)) as client:
        state = client.app.state.trading
        # The test double represents an authenticated private exchange after
        # AppState's normal live-trading/key promotion gate.
        state.data_sources["binance_usdm"] = source
        state.exchanges["binance_usdm"] = source
        state.trading_exchanges["binance_usdm"] = source

        decision = client.get(
            "/api/v1/bot/autopilot/analysis",
            params={"exchange": "binance_usdm", "symbol": "BTCUSDT"},
        )
        assert decision.status_code == 200
        decision_payload = decision.json()

        response = client.post(
            "/api/v1/bot/autopilot/order",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "side": "buy",
                "notional": 25.0,
                "decision_id": decision_payload["decision_id"],
            },
        )
        # A scheduler restart generates another decision ID for the same closed
        # candle, but it must replay the existing execution intent instead of
        # consuming another order or another piece of the daily budget.
        repeated_decision = client.get(
            "/api/v1/bot/autopilot/analysis",
            params={"exchange": "binance_usdm", "symbol": "BTCUSDT"},
        ).json()
        replay = client.post(
            "/api/v1/bot/autopilot/order",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "side": "buy",
                "notional": 25.0,
                "decision_id": repeated_decision["decision_id"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["autopilot"] is True
    assert payload["execution_status"] == "filled"
    assert payload["notional"] == 25.0
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["client_order_id"] == payload["client_order_id"]
    assert source.ticker_calls == 1
    assert source.placed == [
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 0.25,
            "price": None,
            "quote_order_qty": None,
            "client_order_id": payload["client_order_id"],
        }
    ]
