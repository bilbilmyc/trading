"""LiveTradingGuard — the TradingGuard port adapter.

Owns the kill switch (runtime toggle) and reads the live_trading_enabled
flag from settings. The pipeline asks `is_open()` before placing any order;
both the API layer and the engine share this single source of truth.

v0.4.3: state transitions are broadcast to registered observers so the
engine can persist them as audit events. Observers are async callables
fired via `asyncio.create_task` so they don't block the guard's own
caller — and failures inside an observer are swallowed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

KillSwitchObserver = Callable[[str, bool], Awaitable[None]]


class LiveTradingGuard:
    def __init__(self, live_trading_enabled: bool) -> None:
        self._live_trading_enabled = bool(live_trading_enabled)
        self._kill_switch_enabled = False
        self._lock = asyncio.Lock()
        self._observers: list[KillSwitchObserver] = []

    def add_observer(self, observer: KillSwitchObserver) -> None:
        """Register an async callback fired on kill-switch state changes.

        Errors in the observer are swallowed — the guard's correctness
        must not depend on the audit path.
        """
        self._observers.append(observer)

    async def is_open(self) -> bool:
        async with self._lock:
            return self._live_trading_enabled and not self._kill_switch_enabled

    def _notify(self, event_type: str, enabled: bool, reason: str | None = None) -> None:
        # Fire-and-forget: schedule each observer as a task. We don't
        # `await` here so the caller (e.g. risk_manager, the API layer)
        # doesn't have to be async.
        for obs in list(self._observers):
            async def _wrap(o: KillSwitchObserver = obs) -> None:
                try:
                    await o(event_type, enabled, reason)
                except Exception:
                    pass
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No event loop — observers are best-effort, drop them
                # silently if there's nowhere to schedule.
                continue
            loop.create_task(_wrap())

    def disable_trading(self, reason: str | None = None) -> None:
        """Engage the kill switch — no live orders of any kind."""

        if self._kill_switch_enabled:
            return
        self._kill_switch_enabled = True
        self._notify("kill_switch_engaged", True, reason=reason)

    def enable_trading(self, reason: str | None = None) -> None:
        """Release the kill switch. live_trading_enabled still gates live orders."""

        if not self._kill_switch_enabled:
            return
        self._kill_switch_enabled = False
        self._notify("kill_switch_disengaged", False, reason=reason)

    @property
    def kill_switch_enabled(self) -> bool:
        return self._kill_switch_enabled

    def set_live_trading_enabled(self, enabled: bool) -> None:
        """Update the live-trading flag (e.g. from settings)."""

        self._live_trading_enabled = bool(enabled)


__all__ = ["LiveTradingGuard", "KillSwitchObserver"]
