"""Tests for equity curve store."""

from app.engine.equity_curve import EquityCurveStore, EquitySnapshot


def _snap(strategy: str, equity: float, ts: str) -> EquitySnapshot:
    return EquitySnapshot(strategy=strategy, equity=equity, timestamp=ts)


def test_record_and_retrieve(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("sma", 10_000.0, "2026-01-01T00:00:00"))
    history = store.history("sma")
    assert len(history) == 1
    assert history[0].equity == 10_000.0


def test_history_ordered_descending(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("a", 100, "2026-01-01T00:00:00"))
    store.record(_snap("a", 110, "2026-01-02T00:00:00"))
    store.record(_snap("a", 120, "2026-01-03T00:00:00"))
    history = store.history("a")
    assert [s.equity for s in history] == [120, 110, 100]


def test_per_strategy_separation(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("alpha", 100, "2026-01-01T00:00:00"))
    store.record(_snap("beta", 200, "2026-01-01T00:00:00"))
    assert store.history("alpha")[0].equity == 100
    assert store.history("beta")[0].equity == 200


def test_latest_returns_most_recent(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("a", 100, "2026-01-01T00:00:00"))
    store.record(_snap("a", 110, "2026-01-02T00:00:00"))
    assert store.latest("a").equity == 110


def test_latest_returns_none_for_unknown(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    assert store.latest("nope") is None


def test_history_respects_limit(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    for i in range(50):
        store.record(_snap("a", float(i), f"2026-01-{(i % 28) + 1:02d}T00:00:00"))
    assert len(store.history("a", limit=10)) == 10


def test_history_since_filter(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("a", 100, "2026-01-01T00:00:00"))
    store.record(_snap("a", 110, "2026-01-15T00:00:00"))
    store.record(_snap("a", 120, "2026-02-01T00:00:00"))
    history = store.history("a", since="2026-01-15T00:00:00")
    assert len(history) == 2
    assert history[0].equity == 120  # most recent first


def test_all_strategies_equity_curves(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    store.record(_snap("a", 100, "2026-01-01T00:00:00"))
    store.record(_snap("a", 110, "2026-01-02T00:00:00"))
    store.record(_snap("b", 200, "2026-01-01T00:00:00"))
    curves = store.all_strategies_equity_curves()
    assert "a" in curves
    assert "b" in curves
    assert [s.equity for s in curves["a"]] == [100, 110]


def test_empty_history_returns_empty_list(tmp_path) -> None:
    store = EquityCurveStore(str(tmp_path / "eq.sqlite3"))
    assert store.history("nope") == []
    assert store.all_strategies_equity_curves() == {}
