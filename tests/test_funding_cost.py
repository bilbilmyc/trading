"""Tests for funding cost calculator."""

from app.engine.funding_cost import Side, funding_cost


def test_long_pays_positive_rate() -> None:
    r = funding_cost(10_000, 0.0001, 100, Side.LONG)
    assert r.payment == 100.0


def test_long_receives_negative_rate() -> None:
    r = funding_cost(10_000, -0.0001, 100, Side.LONG)
    assert r.payment == -100.0


def test_short_pays_negative_rate() -> None:
    r = funding_cost(10_000, -0.0001, 100, Side.SHORT)
    assert r.payment == 100.0


def test_short_receives_positive_rate() -> None:
    r = funding_cost(10_000, 0.0001, 100, Side.SHORT)
    assert r.payment == -100.0


def test_zero_periods_no_cost() -> None:
    r = funding_cost(10_000, 0.0001, 0, Side.LONG)
    assert r.payment == 0.0


def test_zero_rate_no_cost() -> None:
    r = funding_cost(10_000, 0.0, 100, Side.LONG)
    assert r.payment == 0.0


def test_apr_equivalent_calculation() -> None:
    r = funding_cost(10_000, 0.0001, 1, Side.LONG, periods_per_year=1095)
    assert abs(r.apr_equivalent - 0.1095) < 0.001


def test_invalid_inputs() -> None:
    import pytest
    with pytest.raises(ValueError):
        funding_cost(-1, 0.0001, 10, Side.LONG)
    with pytest.raises(ValueError):
        funding_cost(10_000, 0.0001, -1, Side.LONG)
