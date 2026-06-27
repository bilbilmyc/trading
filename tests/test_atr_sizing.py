from app.engine.atr_sizing import atr_position_size, compute_atr


def test_compute_atr_constant_prices_zero() -> None:
    """Constant prices → 0 range → 0 ATR."""
    prices = [100] * 20
    atr = compute_atr(prices)
    assert atr == 0.0


def test_compute_atr_short_input() -> None:
    assert compute_atr([100, 101]) > 0


def test_compute_atr_uptrend_positive() -> None:
    prices = [100 + i for i in range(20)]  # monotonic up
    atr = compute_atr(prices)
    assert atr > 0


def test_atr_sizing_basic() -> None:
    r = atr_position_size(
        account_equity=10_000,
        entry_price=100.0,
        atr=2.0,           # 2 USD volatility
        risk_pct=0.02,     # 2% risk = $200
        k_multiple=2.0,    # stop at 2 * ATR = $4
    )
    # stop_distance = 4, qty = 200 / 4 = 50
    assert r.quantity == 50.0
    assert r.risk_amount == 200.0
    assert r.stop_distance == 4.0


def test_atr_sizing_higher_vol_smaller_qty() -> None:
    r_low = atr_position_size(10_000, 100.0, atr=1.0, risk_pct=0.02, k_multiple=2.0)
    r_high = atr_position_size(10_000, 100.0, atr=5.0, risk_pct=0.02, k_multiple=2.0)
    assert r_low.quantity > r_high.quantity


def test_atr_sizing_min_quantity_floor() -> None:
    r = atr_position_size(
        account_equity=10,
        entry_price=50_000.0,
        atr=10_000.0,  # extreme volatility
        risk_pct=0.01,
    )
    # Even tiny positions respect min_quantity.
    assert r.quantity >= 0.001


def test_atr_sizing_rejects_zero_atr() -> None:
    r = atr_position_size(10_000, 100.0, atr=0.0, risk_pct=0.02)
    assert r.quantity == 0.0


def test_atr_sizing_rejects_invalid_inputs() -> None:
    import pytest
    with pytest.raises(ValueError):
        atr_position_size(10_000, 100.0, atr=2.0, risk_pct=0.0)
    with pytest.raises(ValueError):
        atr_position_size(10_000, 100.0, atr=2.0, risk_pct=1.5)
    with pytest.raises(ValueError):
        atr_position_size(10_000, 100.0, atr=2.0, k_multiple=0.0)


def test_atr_sizing_higher_risk_pct_larger_qty() -> None:
    r_low = atr_position_size(10_000, 100.0, atr=2.0, risk_pct=0.01, k_multiple=2.0)
    r_high = atr_position_size(10_000, 100.0, atr=2.0, risk_pct=0.05, k_multiple=2.0)
    assert r_high.quantity > r_low.quantity
