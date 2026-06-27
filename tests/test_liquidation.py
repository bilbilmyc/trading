from app.engine.liquidation import (
    Side,
    liquidation_price,
    liq_distance_pct,
)


def test_long_liquidation_below_entry() -> None:
    r = liquidation_price(entry_price=100.0, leverage=10.0, side=Side.LONG)
    # 10x long: liq ≈ entry * (1 - 0.1 + 0.005) = 90.5
    assert r.liquidation_price < r.entry_price
    assert abs(r.liquidation_price - 90.5) < 0.01


def test_short_liquidation_above_entry() -> None:
    r = liquidation_price(entry_price=100.0, leverage=10.0, side=Side.SHORT)
    # 10x short: liq ≈ entry * (1 + 0.1 - 0.005) = 109.5
    assert r.liquidation_price > r.entry_price
    assert abs(r.liquidation_price - 109.5) < 0.01


def test_higher_leverage_closer_liquidation() -> None:
    """More leverage → tighter distance to liquidation."""
    r_low = liquidation_price(entry_price=100.0, leverage=2.0, side=Side.LONG)
    r_high = liquidation_price(entry_price=100.0, leverage=20.0, side=Side.LONG)
    assert r_high.distance_pct < r_low.distance_pct


def test_margin_required_scales_with_leverage() -> None:
    r2 = liquidation_price(entry_price=100.0, leverage=2.0, side=Side.LONG)
    r5 = liquidation_price(entry_price=100.0, leverage=5.0, side=Side.LONG)
    # Higher leverage = lower margin required
    assert r5.margin_required == 20.0
    assert r2.margin_required == 50.0


def test_distance_pct_calculation() -> None:
    r = liquidation_price(entry_price=100.0, leverage=10.0, side=Side.LONG)
    # distance ≈ 0.095
    assert r.distance_pct > 0.05


def test_invalid_leverage_rejected() -> None:
    import pytest
    with pytest.raises(ValueError):
        liquidation_price(entry_price=100.0, leverage=1.0, side=Side.LONG)
    with pytest.raises(ValueError):
        liquidation_price(entry_price=100.0, leverage=0.0, side=Side.LONG)


def test_invalid_price_rejected() -> None:
    import pytest
    with pytest.raises(ValueError):
        liquidation_price(entry_price=0.0, leverage=10.0, side=Side.LONG)
    with pytest.raises(ValueError):
        liquidation_price(entry_price=-100.0, leverage=10.0, side=Side.LONG)


def test_maintenance_margin_increases_liquidation_distance() -> None:
    r_low = liquidation_price(entry_price=100.0, leverage=10.0, side=Side.LONG, maintenance_margin_rate=0.001)
    r_high = liquidation_price(entry_price=100.0, leverage=10.0, side=Side.LONG, maintenance_margin_rate=0.05)
    # Higher MMR → safer position (liq further from entry for long)
    assert r_high.liquidation_price > r_low.liquidation_price


def test_liq_distance_pct_zero_when_safe() -> None:
    """Long position way above liq → distance > 0."""
    d = liq_distance_pct(entry_price=100.0, mark_price=200.0, leverage=10.0, side=Side.LONG)
    assert d > 0


def test_liq_distance_pct_zero_when_below_liq() -> None:
    """Long position crashed past liq → distance clamped to 0."""
    d = liq_distance_pct(entry_price=100.0, mark_price=50.0, leverage=10.0, side=Side.LONG)
    assert d == 0.0


def test_short_liq_distance() -> None:
    """Short position: distance shrinks as price rises."""
    d_safe = liq_distance_pct(entry_price=100.0, mark_price=50.0, leverage=10.0, side=Side.SHORT)
    d_danger = liq_distance_pct(entry_price=100.0, mark_price=105.0, leverage=10.0, side=Side.SHORT)
    assert d_safe > 0
    assert d_danger < d_safe
