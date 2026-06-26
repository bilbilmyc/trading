"""Tests for PriceAlertMonitor — threshold cross detection."""

from __future__ import annotations

from app.engine.price_alerts import (
    AlertDirection,
    FiredAlert,
    PriceAlertMonitor,
    PriceAlertRule,
)


def _rule(id_: str, symbol: str, direction: AlertDirection, threshold: float) -> PriceAlertRule:
    return PriceAlertRule(id=id_, symbol=symbol, exchange="binance_usdm", direction=direction, threshold=threshold)


def test_above_threshold_fires_when_crossed() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    fired = m.tick({"BTCUSDT": 100_500.0})
    assert len(fired) == 1
    assert fired[0].rule_id == "r1"
    assert fired[0].price == 100_500.0


def test_below_threshold_fires_when_crossed() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.BELOW, 100_000.0))
    fired = m.tick({"BTCUSDT": 99_500.0})
    assert len(fired) == 1
    assert fired[0].price == 99_500.0


def test_no_fire_when_threshold_not_crossed() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    fired = m.tick({"BTCUSDT": 99_500.0})
    assert fired == []


def test_repeat_fire_requires_recross() -> None:
    """Once fired at price P, don't refire at P; need price to leave and re-cross."""
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    # First tick above threshold → fires.
    assert len(m.tick({"BTCUSDT": 100_500.0})) == 1
    # Same price → no refire.
    assert len(m.tick({"BTCUSDT": 100_500.0})) == 0
    # Drop below then re-cross → fires again.
    assert len(m.tick({"BTCUSDT": 99_500.0})) == 0
    assert len(m.tick({"BTCUSDT": 101_000.0})) == 1


def test_disabled_rule_does_not_fire() -> None:
    m = PriceAlertMonitor()
    rule = _rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0)
    rule.enabled = False
    m.add(rule)
    assert m.tick({"BTCUSDT": 105_000.0}) == []


def test_missing_price_in_tick_skips_rule() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    fired = m.tick({})  # no prices
    assert fired == []


def test_multiple_rules_in_one_tick() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    m.add(_rule("r2", "ETHUSDT", AlertDirection.BELOW, 4_000.0))
    m.add(_rule("r3", "BTCUSDT", AlertDirection.ABOVE, 200_000.0))  # not crossed

    fired = m.tick({"BTCUSDT": 101_000.0, "ETHUSDT": 3_900.0})
    rule_ids = {f.rule_id for f in fired}
    assert rule_ids == {"r1", "r2"}


def test_remove_rule() -> None:
    m = PriceAlertMonitor()
    m.add(_rule("r1", "BTCUSDT", AlertDirection.ABOVE, 100_000.0))
    assert m.remove("r1") is True
    assert m.remove("r1") is False  # already gone
    assert m.list() == []