"""Tests that the three mode layers are consistent.

The codebase has three places that mention strategy mode:
  1. `LLMStrategyCreateRequest` API Pydantic model  → pattern: signal|paper|live
  2. `StrategyModeRequest` API Pydantic model         → pattern: signal|paper
  3. `TradingEngine.set_strategy_mode()`              → validates {"signal", "paper"}

Originally (1) accepted `live` while (2) and (3) did not. Submitting
`mode="live"` to (1) would silently store a value the engine refuses
to apply later — the strategy would be created but stuck in the
default "signal" mode.

These tests pin the consistent behavior: all three accept the same
set, and switching mode through any path works for all three values.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        sqlite_path=str(tmp_path / "h.sqlite3"),
        enable_live_trading=False,  # important: live mode is allowed at API
        # level but actual execution is gated by this global flag
        frontend_static_dir=str(tmp_path / "static"),
        llm_api_key="",
        okx_enabled=False,
        binance_enabled=False,
        binance_usdm_enabled=True,
        bitget_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ── Engine-level ──────────────────────────────────────────────────


def test_set_strategy_mode_accepts_signal_paper_live(tmp_path) -> None:
    """Engine must accept all three mode values consistently.

    Previously: `set_strategy_mode` rejected "live" with ValueError, while
    the LLM create endpoint accepted it. Now: all three values are stored.
    """
    from app.api.server import create_app as _create

    app = _create(_settings(tmp_path))
    with TestClient(app) as c:
        state = app.state.trading
        # Register a strategy first (any kind) so we can change its mode
        from app.strategies.sma import SMAStrategy
        strat = SMAStrategy(short_window=5, long_window=20)
        state.engine.add_strategy(
            "sma_test", strat,
            exchange="binance_usdm", symbol="BTCUSDT",
            interval="1h", enabled=True, mode="signal",
        )

        for mode in ("signal", "paper", "live"):
            r = state.engine.set_strategy_mode("sma_test", mode)
            assert r["mode"] == mode, f"mode {mode!r} did not stick: {r}"


def test_set_strategy_mode_still_rejects_unknown_value(tmp_path) -> None:
    """Consistency must not mean opening the floodgates to any string.

    "garbage" must still be rejected — otherwise typos like "liev" or
    "papr" would silently set a wrong mode.
    """
    app = create_app(_settings(tmp_path))
    with TestClient(app) as c:
        state = app.state.trading
        from app.strategies.sma import SMAStrategy
        strat = SMAStrategy(short_window=5, long_window=20)
        state.engine.add_strategy(
            "sma_test", strat,
            exchange="binance_usdm", symbol="BTCUSDT",
            interval="1h", enabled=True, mode="signal",
        )
        with pytest.raises(ValueError, match="mode must be one of"):
            state.engine.set_strategy_mode("sma_test", "garbage")


# ── API-level: switch-mode endpoint ───────────────────────────────


def test_api_strategy_mode_endpoint_accepts_live(tmp_path) -> None:
    """POST /api/v1/strategies/{name}/mode must accept "live".

    The Pydantic pattern for `StrategyModeRequest` previously only
    allowed signal|paper, rejecting live with 422. Now: all three pass.
    """
    app = create_app(_settings(tmp_path))
    with TestClient(app) as c:
        state = app.state.trading
        from app.strategies.sma import SMAStrategy
        strat = SMAStrategy(short_window=5, long_window=20)
        state.engine.add_strategy(
            "sma_test", strat,
            exchange="binance_usdm", symbol="BTCUSDT",
            interval="1h", enabled=True, mode="signal",
        )
        # All three values must succeed (the endpoint delegates to engine)
        for mode in ("signal", "paper", "live"):
            r = c.post(
                f"/api/v1/strategies/sma_test/mode",
                json={"mode": mode},
            )
            assert r.status_code == 200, f"{mode!r} got {r.status_code}: {r.text}"
            assert r.json()["strategy"]["mode"] == mode


def test_api_strategy_mode_endpoint_rejects_unknown(tmp_path) -> None:
    """Pydantic pattern check is the API-layer gate; the engine gate
    is a defense-in-depth. Both must reject unknown values."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as c:
        state = app.state.trading
        from app.strategies.sma import SMAStrategy
        strat = SMAStrategy(short_window=5, long_window=20)
        state.engine.add_strategy(
            "sma_test", strat,
            exchange="binance_usdm", symbol="BTCUSDT",
            interval="1h", enabled=True, mode="signal",
        )
        r = c.post(
            f"/api/v1/strategies/sma_test/mode",
            json={"mode": "garbage"},
        )
        assert r.status_code == 422
