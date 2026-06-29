"""Webhook notifier — POST events to a configurable URL.

Generic for Telegram / Discord / Slack / custom. Single endpoint,
text payload by default. Async + non-blocking; failures are logged
but never raised (notifications should not break the trading loop).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class NotificationEvent:
    title: str
    message: str
    severity: str = "info"     # "info" | "warning" | "critical"
    timestamp: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class WebhookNotifier:
    """POSTs NotificationEvents to a configured webhook URL.

    `enabled=False` short-circuits; safe to call regardless. Keeps a
    bounded in-memory log of the last N deliveries for debugging.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        enabled: bool = False,
        timeout_seconds: float = 5.0,
        max_log: int = 100,
    ) -> None:
        self._url = url
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._log: list[dict[str, Any]] = []
        self._max_log = max_log

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._url)

    def configure(self, *, url: str | None = None, enabled: bool | None = None) -> None:
        if url is not None:
            self._url = url
        if enabled is not None:
            self._enabled = enabled

    async def notify(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        payload = {
            "title": event.title,
            "message": event.message,
            "severity": event.severity,
            "timestamp": event.timestamp or _now_iso(),
            "extra": event.extra,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url,  # type: ignore[arg-type]
                    json=payload,
                )
                self._record({
                    "ts": payload["timestamp"],
                    "ok": 200 <= resp.status_code < 300,
                    "status": resp.status_code,
                    "title": event.title,
                })
                return 200 <= resp.status_code < 300
        except Exception as exc:
            self._record({
                "ts": payload["timestamp"],
                "ok": False,
                "error": str(exc),
                "title": event.title,
            })
            return False

    def notify_sync(self, event: NotificationEvent) -> bool:
        """Fire-and-forget from sync code — schedules the async send."""
        if not self.enabled:
            return False
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.notify(event))
            return True
        except RuntimeError:
            # No running loop (e.g., from CLI subcommand). Best-effort sync run.
            return asyncio.run(self.notify(event))

    def _record(self, entry: dict[str, Any]) -> None:
        self._log.append(entry)
        if len(self._log) > self._max_log:
            self._log = self._log[-self._max_log :]

    def log(self) -> list[dict[str, Any]]:
        return list(self._log)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


__all__ = ["NotificationEvent", "WebhookNotifier"]
