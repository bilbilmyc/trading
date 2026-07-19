"""Portfolio-level gross-exposure snapshots used by pre-trade risk checks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol


class ExposurePosition(Protocol):
    """Minimal position shape required for gross-notional aggregation."""

    symbol: str
    quantity: float
    current_price: float
    avg_entry_price: float


@dataclass(frozen=True)
class PortfolioExposure:
    """Gross notional exposure aggregated by normalized asset symbol.

    Gross values intentionally use absolute quantities: a long and a short on
    separate venues still consume exposure capacity until a future netting
    policy explicitly models their hedge relationship.
    """

    total_notional: float = 0.0
    by_symbol: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_positions(
        cls,
        positions: Iterable[ExposurePosition],
        *,
        price_overrides: dict[str, float] | None = None,
    ) -> PortfolioExposure:
        """Build a conservative gross-exposure snapshot from local positions."""
        overrides = {symbol.upper(): price for symbol, price in (price_overrides or {}).items()}
        by_symbol: dict[str, float] = {}
        for position in positions:
            symbol = position.symbol.upper()
            price = overrides.get(symbol, position.current_price or position.avg_entry_price)
            if not price or not position.quantity:
                continue
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + abs(position.quantity) * price
        return cls(total_notional=sum(by_symbol.values()), by_symbol=by_symbol)

    def projected(self, symbol: str, additional_notional: float) -> PortfolioExposure:
        """Return the snapshot after a new order increases gross exposure."""
        normalized_symbol = symbol.upper()
        by_symbol = dict(self.by_symbol)
        by_symbol[normalized_symbol] = by_symbol.get(normalized_symbol, 0.0) + additional_notional
        return PortfolioExposure(
            total_notional=self.total_notional + additional_notional,
            by_symbol=by_symbol,
        )

    def concentration(self, symbol: str) -> float:
        """Return an asset's share of gross exposure, or zero for an empty book."""
        if self.total_notional <= 0:
            return 0.0
        return self.by_symbol.get(symbol.upper(), 0.0) / self.total_notional

    def group_notional(self, symbols: Iterable[str]) -> float:
        """Return gross notional for the configured symbols in one asset group."""
        normalized_symbols = {symbol.upper() for symbol in symbols}
        return sum(
            notional
            for symbol, notional in self.by_symbol.items()
            if symbol.upper() in normalized_symbols
        )

    def group_concentration(self, symbols: Iterable[str]) -> float:
        """Return one configured asset group's share of gross exposure."""
        if self.total_notional <= 0:
            return 0.0
        return self.group_notional(symbols) / self.total_notional

    def as_dict(self) -> dict[str, object]:
        """Return JSON-friendly state for status and audit surfaces."""
        return {
            "total_notional": self.total_notional,
            "by_symbol": dict(sorted(self.by_symbol.items())),
        }


__all__ = ["PortfolioExposure", "ExposurePosition"]
