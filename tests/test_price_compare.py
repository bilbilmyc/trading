"""Tests for multi-exchange price comparison — same symbol across sources."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.engine.price_compare import (
    PriceQuote,
    compare_symbol,
    best_price,
    spread_bps,
)


def _q(source: str, price: float, bid: float | None = None, ask: float | None = None) -> PriceQuote:
    return PriceQuote(source=source, price=price, bid=bid, ask=ask)


def test_compare_collects_quotes_per_source() -> None:
    quotes = compare_symbol(
        symbol="BTCUSDT",
        sources=["binance_usdm", "okx_swap", "bitget_usdt_futures"],
        fetcher=lambda src, sym: _q(src, 100_000.0),
    )
    assert len(quotes) == 3
    assert {q.source for q in quotes} == {"binance_usdm", "okx_swap", "bitget_usdt_futures"}


def test_compare_skips_failed_sources() -> None:
    def fetch(src, sym):
        if src == "okx_swap":
            raise RuntimeError("upstream timeout")
        return _q(src, 100_000.0)

    quotes = compare_symbol(symbol="BTCUSDT", sources=["binance_usdm", "okx_swap"], fetcher=fetch)
    assert len(quotes) == 1
    assert quotes[0].source == "binance_usdm"


def test_best_price_returns_lowest_ask_for_buy() -> None:
    quotes = [
        _q("a", 100, bid=99, ask=101),
        _q("b", 100, bid=99, ask=99.5),
        _q("c", 100, bid=99, ask=100.5),
    ]
    best = best_price(quotes, side="buy")
    assert best is not None
    assert best.source == "b"
    assert best.ask == 99.5


def test_best_price_returns_highest_bid_for_sell() -> None:
    quotes = [
        _q("a", 100, bid=99, ask=101),
        _q("b", 100, bid=100.5, ask=101.5),
        _q("c", 100, bid=99.5, ask=100.5),
    ]
    best = best_price(quotes, side="sell")
    assert best is not None
    assert best.source == "b"
    assert best.bid == 100.5


def test_best_price_returns_none_when_no_quotes_have_quote_side() -> None:
    quotes = [_q("a", 100), _q("b", 100)]
    assert best_price(quotes, side="buy") is None


def test_spread_bps_calculation() -> None:
    q = _q("x", 100, bid=99, ask=101)
    assert spread_bps(q) == 200.0  # 2 / 100 * 10000


def test_spread_bps_zero_when_only_mid() -> None:
    q = _q("x", 100)
    assert spread_bps(q) == 0.0


def test_spread_arbitrage_opportunity_detected() -> None:
    """Best ask < best bid across two venues → arb."""
    quotes = [
        _q("a", 100, bid=100.5, ask=101),
        _q("b", 100, bid=99, ask=99.5),
    ]
    best_buy = best_price(quotes, side="buy")
    best_sell = best_price(quotes, side="sell")
    assert best_buy.source == "b"
    assert best_sell.source == "a"
    assert best_buy.ask < best_sell.bid  # arb: buy on b at 99.5, sell on a at 100.5