from app.engine.kelly_sizing import kelly_fraction


def test_kelly_fair_coin_returns_zero() -> None:
    """50/50 coin at even odds → no edge → Kelly = 0."""
    r = kelly_fraction(0.5, 1.0)
    assert r.full_kelly_pct == 0.0
    assert r.edge == 0.0


def test_kelly_positive_edge() -> None:
    """60% win at 1:1 → Kelly = 0.2 (20% of bankroll)."""
    r = kelly_fraction(0.6, 1.0)
    assert abs(r.full_kelly_pct - 0.2) < 0.01
    assert r.edge > 0


def test_kelly_negative_edge_returns_zero() -> None:
    """30% win at 1:1 → negative edge → Kelly capped at 0."""
    r = kelly_fraction(0.3, 1.0)
    assert r.full_kelly_pct == 0.0
    assert r.edge < 0


def test_kelly_fractional_half_kelly() -> None:
    r = kelly_fraction(0.6, 1.0, fractional=0.5)
    assert abs(r.half_kelly_pct - 0.1) < 0.01
    assert abs(r.full_kelly_pct - 0.2) < 0.01


def test_kelly_2to1_odds() -> None:
    """50% win at 2:1 → Kelly = 0.25."""
    r = kelly_fraction(0.5, 2.0)
    assert abs(r.full_kelly_pct - 0.25) < 0.01


def test_kelly_high_confidence() -> None:
    """80% win at 1:1 → Kelly = 0.6."""
    r = kelly_fraction(0.8, 1.0)
    assert abs(r.full_kelly_pct - 0.6) < 0.01


def test_kelly_invalid_inputs() -> None:
    import pytest
    with pytest.raises(ValueError):
        kelly_fraction(0.0, 1.0)
    with pytest.raises(ValueError):
        kelly_fraction(1.0, 1.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 0.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 1.0, fractional=0.0)


def test_kelly_recommended_pct_in_range() -> None:
    r = kelly_fraction(0.7, 1.5)
    assert 0.0 <= r.recommended_pct <= 1.0


def test_kelly_growth_rate_positive_for_positive_edge() -> None:
    r = kelly_fraction(0.6, 1.0)
    assert r.expected_growth_rate > 0
