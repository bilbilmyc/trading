"""Tests for order book imbalance indicator."""

from app.engine.orderbook_imbalance import (
    ImbalanceLevel,
    orderbook_imbalance,
    orderbook_imbalance_top_n,
)


def test_balanced_book_zero_imbalance() -> None:
    bids = [ImbalanceLevel(100, 1.0), ImbalanceLevel(99, 1.0)]
    asks = [ImbalanceLevel(101, 1.0), ImbalanceLevel(102, 1.0)]
    r = orderbook_imbalance(bids, asks)
    assert r.bid_volume == 2.0
    assert r.ask_volume == 2.0
    assert r.imbalance == 0.0
    assert r.signal == "neutral"


def test_more_bids_signals_buy() -> None:
    bids = [ImbalanceLevel(100, 10.0)]
    asks = [ImbalanceLevel(101, 1.0)]
    r = orderbook_imbalance(bids, asks)
    assert r.imbalance > 0.8
    assert r.signal == "buy"


def test_more_asks_signals_sell() -> None:
    bids = [ImbalanceLevel(100, 1.0)]
    asks = [ImbalanceLevel(101, 10.0)]
    r = orderbook_imbalance(bids, asks)
    assert r.imbalance < -0.8
    assert r.signal == "sell"


def test_empty_book_neutral() -> None:
    r = orderbook_imbalance([], [])
    assert r.imbalance == 0.0
    assert r.signal == "neutral"
    assert r.depth_ratio == 0.0


def test_only_bids_signals_buy() -> None:
    bids = [ImbalanceLevel(100, 5.0)]
    r = orderbook_imbalance(bids, [])
    assert r.signal == "buy"
    assert r.depth_ratio == 9999.0  # sentinel for inf


def test_only_asks_signals_sell() -> None:
    asks = [ImbalanceLevel(101, 5.0)]
    r = orderbook_imbalance([], asks)
    assert r.signal == "sell"


def test_depth_ratio_basic() -> None:
    bids = [ImbalanceLevel(100, 3.0)]
    asks = [ImbalanceLevel(101, 1.0)]
    r = orderbook_imbalance(bids, asks)
    assert r.depth_ratio == 3.0


def test_top_n_truncates_levels() -> None:
    bids = [ImbalanceLevel(100, 1.0)] * 10
    asks = [ImbalanceLevel(101, 1.0)] * 10
    r = orderbook_imbalance_top_n(bids, asks, depth=2)
    # Only first 2 levels used → 2 vs 2 → balanced.
    assert r.imbalance == 0.0


def test_signal_threshold() -> None:
    """Small imbalance (<10%) = neutral."""
    bids = [ImbalanceLevel(100, 1.05)]
    asks = [ImbalanceLevel(101, 1.0)]
    r = orderbook_imbalance(bids, asks)
    assert r.signal == "neutral"
