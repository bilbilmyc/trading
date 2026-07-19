"""Targeted tests for local gross portfolio exposure risk gates."""

from types import SimpleNamespace

import pytest

from app.engine.portfolio_exposure import PortfolioExposure
from app.engine.risk_manager import RiskConfig, RiskManager


@pytest.mark.asyncio
async def test_exposure_snapshot_aggregates_venues_and_uses_order_price_override() -> None:
    positions = [
        SimpleNamespace(
            symbol="BTCUSDT",
            quantity=0.5,
            current_price=100.0,
            avg_entry_price=90.0,
        ),
        SimpleNamespace(
            symbol="btcusdt",
            quantity=-0.25,
            current_price=110.0,
            avg_entry_price=95.0,
        ),
        SimpleNamespace(
            symbol="ETHUSDT",
            quantity=2.0,
            current_price=50.0,
            avg_entry_price=45.0,
        ),
    ]

    exposure = PortfolioExposure.from_positions(
        positions,
        price_overrides={"BTCUSDT": 120.0},
    )

    assert exposure.total_notional == pytest.approx(190.0)
    assert exposure.by_symbol == {"BTCUSDT": 90.0, "ETHUSDT": 100.0}
    assert exposure.concentration("ethusdt") == pytest.approx(100.0 / 190.0)


@pytest.mark.asyncio
async def test_portfolio_cap_blocks_order_that_increases_gross_exposure() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_portfolio_exposure=200.0,
        )
    )

    async def exposure_provider(symbol: str, price: float) -> PortfolioExposure:
        assert (symbol, price) == ("ETHUSDT", 120.0)
        return PortfolioExposure(total_notional=100.0, by_symbol={"BTCUSDT": 100.0})

    manager.set_portfolio_exposure_provider(exposure_provider)
    allowed, reason = await manager.check_order("ETHUSDT", "buy", 1.0, 120.0)

    assert allowed is False
    assert "组合总名义暴露" in reason


@pytest.mark.asyncio
async def test_asset_concentration_cap_blocks_new_concentrated_exposure() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_asset_concentration_pct=0.60,
        )
    )

    async def exposure_provider(symbol: str, price: float) -> PortfolioExposure:
        return PortfolioExposure(
            total_notional=200.0,
            by_symbol={"BTCUSDT": 100.0, "ETHUSDT": 100.0},
        )

    manager.set_portfolio_exposure_provider(exposure_provider)
    allowed, reason = await manager.check_order("BTCUSDT", "buy", 1.0, 100.0)

    assert allowed is False
    assert "单资产 BTCUSDT 暴露占比" in reason


@pytest.mark.asyncio
async def test_reducing_order_bypasses_exposure_caps_and_status_reports_snapshot() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_portfolio_exposure=100.0,
            max_asset_concentration_pct=0.50,
        )
    )
    exposure = PortfolioExposure(
        total_notional=250.0,
        by_symbol={"BTCUSDT": 200.0, "ETHUSDT": 50.0},
    )

    async def exposure_provider(symbol: str, price: float) -> PortfolioExposure:
        return exposure

    manager.set_portfolio_exposure_provider(exposure_provider)
    allowed, reason = await manager.check_order(
        "BTCUSDT",
        "sell",
        1.0,
        100.0,
        increases_exposure=False,
    )
    status = await manager.get_risk_status()

    assert allowed is True
    assert reason == "通过风控检查"
    assert status["portfolio_exposure"] == exposure.as_dict()
    assert status["max_portfolio_exposure"] == 100.0
    assert status["max_asset_concentration_pct"] == 0.50
