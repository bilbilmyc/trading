"""Tests for funding rate tracker."""

from __future__ import annotations

from app.engine.funding import FundingSnapshot, FundingTracker


def test_empty_tracker_returns_none() -> None:
    t = FundingTracker()
    assert t.latest("BTCUSDT", "binance_usdm") is None


def test_record_and_retrieve_latest() -> None:
    t = FundingTracker()
    t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=0.0001))
    snap = t.latest("BTCUSDT", "binance_usdm")
    assert snap is not None
    assert snap.rate == 0.0001


def test_case_insensitive_keys() -> None:
    t = FundingTracker()
    t.record(FundingSnapshot(symbol="btcusdt", exchange="Binance_USDM", rate=0.0002))
    assert t.latest("BTCUSDT", "binance_usdm") is not None


def test_separate_history_per_pair() -> None:
    t = FundingTracker()
    t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=0.0001))
    t.record(FundingSnapshot(symbol="ETHUSDT", exchange="binance_usdm", rate=0.0003))
    assert t.latest("BTCUSDT", "binance_usdm").rate == 0.0001
    assert t.latest("ETHUSDT", "binance_usdm").rate == 0.0003


def test_history_keeps_order() -> None:
    t = FundingTracker()
    for i in range(5):
        t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=float(i) / 10000))
    hist = t.history("BTCUSDT", "binance_usdm")
    rates = [s.rate for s in hist.snapshots]
    assert rates == [0.0, 0.0001, 0.0002, 0.0003, 0.0004]


def test_history_bounded_at_1000() -> None:
    t = FundingTracker()
    for i in range(1500):
        t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=float(i)))
    assert len(t.history("BTCUSDT", "binance_usdm").snapshots) == 1000


def test_annualized_rate_default_3_per_day() -> None:
    t = FundingTracker()
    t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=0.0001))
    annualized = t.history("BTCUSDT", "binance_usdm").annualized_rate()
    # 0.0001 * 3 * 365 = 0.1095
    assert abs(annualized - 0.1095) < 1e-9


def test_all_pairs_returns_distinct_keys() -> None:
    t = FundingTracker()
    t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=0.0001))
    t.record(FundingSnapshot(symbol="ETHUSDT", exchange="okx_swap", rate=0.0002))
    t.record(FundingSnapshot(symbol="BTCUSDT", exchange="binance_usdm", rate=0.0003))
    assert len(t.all_pairs()) == 2


def test_history_empty_annualized_returns_none() -> None:
    from app.engine.funding import FundingHistory

    h = FundingHistory()
    assert h.annualized_rate() is None