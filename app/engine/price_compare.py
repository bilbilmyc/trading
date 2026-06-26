"""Multi-exchange price comparison — same symbol across data sources.

Used for arbitrage detection and best-execution routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PriceQuote:
    source: str
    price: float             # mid price (always populated)
    bid: Optional[float] = None
    ask: Optional[float] = None


# Fetcher: (source_name, symbol) -> PriceQuote
Fetcher = Callable[[str, str], PriceQuote]


def compare_symbol(
    *,
    symbol: str,
    sources: List[str],
    fetcher: Fetcher,
) -> List[PriceQuote]:
    """Fetch the same symbol from each source; skip sources that fail.

    Failures are silently skipped — one bad source shouldn't block
    arbitrage view from the others.
    """
    quotes: List[PriceQuote] = []
    for src in sources:
        try:
            q = fetcher(src, symbol)
            quotes.append(q)
        except Exception:
            continue
    return quotes


def best_price(quotes: List[PriceQuote], *, side: str) -> Optional[PriceQuote]:
    """Return the venue with the best executable price for `side` ("buy" or "sell").

    For "buy", minimize `ask` (cheapest to lift). For "sell", maximize
    `bid` (highest to hit). Returns None when no quote has the needed side.
    """
    if side == "buy":
        candidates = [q for q in quotes if q.ask is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda q: q.ask)  # type: ignore[arg-type,return-value]
    elif side == "sell":
        candidates = [q for q in quotes if q.bid is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda q: q.bid)  # type: ignore[arg-type,return-value]
    return None


def spread_bps(quote: PriceQuote) -> float:
    """Bid/ask spread in basis points (1bp = 0.01%)."""
    if quote.bid is None or quote.ask is None or quote.price <= 0:
        return 0.0
    return (quote.ask - quote.bid) / quote.price * 10_000


__all__ = ["PriceQuote", "Fetcher", "compare_symbol", "best_price", "spread_bps"]