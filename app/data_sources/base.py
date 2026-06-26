"""DataSource — public market data seam.

Public endpoints (ticker, klines, recent trades) work without any API
key. This Protocol is the minimum surface every data source must
implement, regardless of whether it is also a trading exchange.

Any object with `name` and async `get_ticker` / `get_klines` /
`get_recent_trades` conforms structurally. `ExchangeBase` already
satisfies this; custom (CCXT, HTTP, file-backed) sources can be plugged
in by implementing the same shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol


class DataSource(Protocol):
    """Read-only public market data interface."""

    name: str

    async def get_ticker(self, symbol: str) -> Dict[str, Any]: ...

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 100,
    ) -> List[Dict[str, Any]]: ...

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]: ...


__all__ = ["DataSource"]