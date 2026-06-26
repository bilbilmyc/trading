"""LiveTradingGuard — the TradingGuard port adapter.

Owns the kill switch (runtime toggle) and reads the live_trading_enabled
flag from settings. The pipeline asks `is_open()` before placing any order;
both the API layer and the engine share this single source of truth.
"""

from __future__ import annotations

import asyncio


class LiveTradingGuard:
    def __init__(self, live_trading_enabled: bool) -> None:
        self._live_trading_enabled = bool(live_trading_enabled)
        self._kill_switch_enabled = False
        self._lock = asyncio.Lock()

    async def is_open(self) -> bool:
        async with self._lock:
            return self._live_trading_enabled and not self._kill_switch_enabled

    def disable_trading(self) -> None:
        """Engage the kill switch — no live orders of any kind."""

        self._kill_switch_enabled = True

    def enable_trading(self) -> None:
        """Release the kill switch. live_trading_enabled still gates live orders."""

        self._kill_switch_enabled = False

    @property
    def kill_switch_enabled(self) -> bool:
        return self._kill_switch_enabled

    def set_live_trading_enabled(self, enabled: bool) -> None:
        """Update the live-trading flag (e.g. from settings)."""

        self._live_trading_enabled = bool(enabled)


__all__ = ["LiveTradingGuard"]