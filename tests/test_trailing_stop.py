from app.engine.trailing_stop import Side, TrailingStop


def test_long_stop_initial_state() -> None:
    ts = TrailingStop(side=Side.LONG, entry_price=100.0)
    assert ts.current_stop is None
    assert not ts.triggered
    assert not ts.hit


def test_long_stop_triggers_on_drop_below_stop() -> None:
    ts = TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=0.05, activation_pct=0.0)
    # Price rises — stop should ratchet up.
    hit = ts.update(110.0)
    assert not hit
    assert ts.current_stop is not None
    assert ts.current_stop > 100.0  # ratcheted up
    # Price drops to stop → trigger.
    hit = ts.update(ts.current_stop - 0.01)
    assert hit
    assert ts.hit


def test_short_stop_triggers_on_rise_above_stop() -> None:
    ts = TrailingStop(side=Side.SHORT, entry_price=100.0, ratchet_pct=0.05, activation_pct=0.0)
    # Price drops — stop should ratchet down.
    ts.update(90.0)
    assert ts.current_stop is not None
    assert ts.current_stop < 100.0
    # Price rises to stop → trigger.
    hit = ts.update(ts.current_stop + 0.01)
    assert hit


def test_long_stop_never_loosens() -> None:
    """Stop can only ratchet up, never down."""
    ts = TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=0.05, activation_pct=0.0)
    ts.update(120.0)
    stop_after_up = ts.current_stop
    ts.update(110.0)  # price drops
    assert ts.current_stop >= stop_after_up - 1e-9  # allow float precision


def test_activation_threshold() -> None:
    """Stop doesn't activate until profit exceeds activation_pct."""
    ts = TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=0.05, activation_pct=0.10)
    # 5% profit — below 10% activation threshold.
    ts.update(105.0)
    assert ts.current_stop is None
    assert not ts.triggered
    # 12% profit — above threshold.
    ts.update(112.0)
    assert ts.triggered
    assert ts.current_stop is not None


def test_unrealized_pnl_long() -> None:
    ts = TrailingStop(side=Side.LONG, entry_price=100.0)
    assert ts.unrealized_pnl(110.0) == 10.0
    assert ts.unrealized_pnl(95.0) == -5.0


def test_unrealized_pnl_short() -> None:
    ts = TrailingStop(side=Side.SHORT, entry_price=100.0)
    assert ts.unrealized_pnl(90.0) == 10.0
    assert ts.unrealized_pnl(110.0) == -10.0


def test_invalid_ratchet_rejected() -> None:
    import pytest
    with pytest.raises(ValueError):
        TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=1.5)
    with pytest.raises(ValueError):
        TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=-0.1)


def test_hit_once_stays_hit() -> None:
    ts = TrailingStop(side=Side.LONG, entry_price=100.0, ratchet_pct=0.05, activation_pct=0.0)
    ts.update(120.0)
    ts.update(80.0)  # triggers
    assert ts.hit
    hit_again = ts.update(150.0)  # price recovers — still hit
    assert hit_again is True
