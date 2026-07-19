"""Targeted tests for local gross portfolio exposure risk gates."""

from types import SimpleNamespace

import pytest

from app.engine.portfolio_exposure import PortfolioExposure
from app.engine.risk_manager import RiskConfig, RiskManager
from config.settings import Settings


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


@pytest.mark.asyncio
async def test_asset_group_concentration_blocks_grouped_assets_and_reports_status() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_asset_group_concentration_pct=0.55,
            asset_groups={"layer1": ("BTCUSDT", "ETHUSDT")},
        )
    )
    exposure = PortfolioExposure(
        total_notional=300.0,
        by_symbol={"BTCUSDT": 100.0, "ETHUSDT": 80.0, "SOLUSDT": 120.0},
    )

    async def exposure_provider(symbol: str, price: float) -> PortfolioExposure:
        return exposure

    manager.set_portfolio_exposure_provider(exposure_provider)
    blocked, reason = await manager.check_order("ETHUSDT", "buy", 1.0, 20.0)
    allowed, allowed_reason = await manager.check_order("SOLUSDT", "buy", 1.0, 20.0)
    status = await manager.get_risk_status()

    assert blocked is False
    assert "资产分组 layer1 暴露占比" in reason
    assert allowed is True
    assert allowed_reason == "通过风控检查"
    assert status["max_asset_group_concentration_pct"] == 0.55
    assert status["asset_groups"] == {"layer1": ["BTCUSDT", "ETHUSDT"]}
    assert status["asset_group_exposure"]["layer1"] == {
        "notional": 180.0,
        "concentration": 0.6,
    }


def test_asset_group_mapping_is_normalized_and_rejects_ambiguous_symbols() -> None:
    config = RiskConfig(asset_groups={"layer1": ("btcusdt", "ETHUSDT")})

    assert config.asset_groups == {"layer1": ("BTCUSDT", "ETHUSDT")}
    with pytest.raises(ValueError, match="只能属于一个资产分组"):
        RiskConfig(
            asset_groups={
                "layer1": ("BTCUSDT",),
                "large_cap": ("btcusdt", "SOLUSDT"),
            }
        )


def test_settings_passes_asset_group_limits_to_risk_config() -> None:
    settings = Settings(
        max_asset_group_concentration_pct=0.7,
        risk_asset_groups={"layer1": ("BTCUSDT", "ETHUSDT")},
    )

    risk = settings.risk

    assert risk.max_asset_group_concentration_pct == 0.7
    assert risk.asset_groups == {"layer1": ("BTCUSDT", "ETHUSDT")}
