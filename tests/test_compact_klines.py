"""Tests for compact K-line encoding in LLMAnalyzer.

The old prompt shipped K-lines as ~80-char aligned rows. The compact
format reduces payload by ~50% (40 chars per row) and includes a summary
header (count, first/last close, ATR, range) so the LLM has the same
context in fewer tokens.
"""

from __future__ import annotations

from datetime import datetime

from app.engine.llm_types import LLMDecided
from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig
from app.strategies.base import Signal, SignalAction


def _analyzer(**overrides):
    cfg = LLMAnalyzerConfig(api_key="dummy", **overrides)
    return LLMAnalyzer(config=cfg)


def _klines(n: int = 30, start_price: float = 100.0) -> list:
    """Generate n ascending K-lines from start_price (newest first)."""
    return [
        {
            "open_time": datetime(2026, 6, 26, 14, 0, 0),
            "open": start_price + i,
            "high": start_price + i + 1,
            "low": start_price + i - 1,
            "close": start_price + i + 0.5,
            "volume": 10.0 + i,
        }
        for i in range(n)
    ]


def test_compact_kline_format_is_shorter_than_pretty() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer()
    rows = _klines(30)
    compact = analyzer._render_klines_compact(rows)

    # Each compact line should be < 60 chars (vs ~80 in pretty format).
    lines = compact.splitlines()
    assert lines[0].startswith("#K")  # summary header
    for line in lines[1:]:
        assert len(line) < 60, f"line too long: {line!r}"


def test_compact_kline_summary_includes_count_and_price_range() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer()
    rows = _klines(30)
    compact = analyzer._render_klines_compact(rows)
    header = compact.splitlines()[0]

    # Header carries count and price extremes for orientation.
    assert "30" in header
    assert "first=" in header
    assert "last=" in header


def test_compact_kline_body_uses_short_field_prefixes() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer()
    rows = _klines(3)
    compact = analyzer._render_klines_compact(rows)
    body = compact.splitlines()[1:]
    for line in body:
        # Each line has at least o/h/l/c/v fields with short prefixes.
        for prefix in ("o:", "h:", "l:", "c:", "v:"):
            assert prefix in line, f"missing {prefix} in {line!r}"


def test_compact_format_handles_empty_input() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer()
    assert analyzer._render_klines_compact([]) == ""


def test_compact_format_truncates_to_max_rows() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer(max_compact_rows=5)
    rows = _klines(100)
    compact = analyzer._render_klines_compact(rows)
    body_lines = compact.splitlines()[1:]
    assert len(body_lines) == 5


def test_prompt_template_renders_with_compact_klines() -> None:
    """End-to-end: analyzer._build_prompt produces a prompt that contains
    the compact K-line block, not the old aligned table."""
    from app.strategies.llm_analyzer import LLMAnalyzer, PROMPT_TEMPLATE

    analyzer = _analyzer()
    signal = Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.001)
    prompt = analyzer._build_prompt(
        symbol="BTCUSDT",
        interval="1h",
        ticker={"last_price": 100.0, "price_change_pct_24h": 0.0,
                "volume_24h": 1000, "quote_volume_24h": 100000},
        klines=_klines(20),
        position_context=None,
    )

    # Compact format markers present.
    assert "#K n=" in prompt
    assert "o:" in prompt and "h:" in prompt
    # Old aligned-format header NOT present.
    assert "open_time    open      high" not in prompt


def test_summary_metrics_computed_from_klines() -> None:
    from app.strategies.llm_analyzer import LLMAnalyzer

    analyzer = _analyzer()
    rows = _klines(30, start_price=100.0)
    summary = analyzer._kline_summary(rows)

    assert summary["count"] == 30
    assert summary["first_close"] == 100.5
    assert summary["last_close"] == 129.5
    assert summary["max_high"] == 130.0  # 100+29+1
    assert summary["min_low"] == 99.0   # 100+0-1
    assert summary["atr"] > 0