"""GenericHttpDataSource — register any HTTP API as a DataSource.

The user supplies a base URL plus a path template and a field map that
translates the provider's JSON shape into the canonical DataSource
contract. Used by the frontend "Add custom source" form (ADR-0003).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import httpx


class GenericHttpDataSource:
    """Public-market HTTP adapter with user-supplied field mapping."""

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        ticker_path: str = "/ticker/{symbol}",
        klines_path: str = "/klines",
        trades_path: str = "/trades",
        ticker_field_map: Optional[Mapping[str, str]] = None,
        klines_field_map: Optional[Mapping[str, str]] = None,
        klines_array_key: Optional[str] = None,  # if response is wrapped
        timeout_seconds: float = 10.0,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._ticker_path = ticker_path
        self._klines_path = klines_path
        self._trades_path = trades_path
        self._ticker_map = dict(ticker_field_map or {"last_price": "last_price", "volume_24h": "volume_24h"})
        self._klines_map = dict(klines_field_map or {
            "open_time": "open_time", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
        })
        self._klines_array_key = klines_array_key
        self._timeout = timeout_seconds
        self._headers = dict(headers or {})

    def _url(self, path: str, symbol: str, query: Optional[Dict[str, Any]] = None) -> str:
        if "{symbol}" in path:
            rendered = path.replace("{symbol}", symbol)
        else:
            # No placeholder — append as ?symbol=... so any provider works.
            rendered = path
            query = {"symbol": symbol, **(query or {})}
        url = f"{self._base_url}{rendered}"
        if query:
            from urllib.parse import urlencode
            url += "?" + urlencode(query)
        return url

    async def _get_json(self, url: str) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    def _remap(self, src: Mapping[str, Any], field_map: Mapping[str, str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for target, src_field in field_map.items():
            if src_field in src:
                out[target] = src[src_field]
        return out

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        url = self._url(self._ticker_path, symbol)
        data = await self._get_json(url)
        if not isinstance(data, Mapping):
            return {}
        return self._remap(data, self._ticker_map)

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        url = self._url(self._klines_path, symbol, {"interval": interval, "limit": str(limit)})
        data = await self._get_json(url)
        rows: List[Any]
        if self._klines_array_key and isinstance(data, Mapping):
            rows = data.get(self._klines_array_key, [])
        else:
            rows = data if isinstance(data, list) else []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, Mapping):
                out.append(self._remap(row, self._klines_map))
        return out

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        url = self._url(self._trades_path, symbol, {"limit": str(limit)})
        data = await self._get_json(url)
        if not isinstance(data, list):
            return []
        return [dict(row) for row in data if isinstance(row, Mapping)]


__all__ = ["GenericHttpDataSource"]