"""Alert dispatcher — push Monitor alerts to Feishu / DingTalk / WeCom.

The dispatcher hooks into the Monitor's callback system (`on_alert`)
and fans out to one or more enabled providers. Each provider is a
thin wrapper around a webhook URL — no SDK, just a POST with a
provider-specific JSON payload.

Supported providers (all three are bot webhook integrations, so no
auth/secret beyond the webhook URL itself):

  - Feishu (Lark)  — `msg_type=text`, `content.text`
  - DingTalk        — `msgtype=text`,  `text.content`
  - WeCom (企业微信) — `msgtype=text`, `text.content`

Webhook setup (in the target chat tool):
  Feishu:   群机器人 → 添加机器人 → 自定义 webhook → 复制 URL
  DingTalk: 群设置 → 智能群助手 → 添加机器人 → 自定义 webhook
  WeCom:    群机器人 → 添加 → 复制 webhook URL
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from loguru import logger

from app.engine.monitor import Alert, AlertCategory, AlertLevel

# ── Provider protocol ────────────────────────────────────────────


class AlertProvider(Protocol):
    """Single notification destination. Implementations are stateless
    and side-effecting (network call)."""

    name: str

    async def send(self, payload: AlertPayload) -> None: ...


@dataclass(frozen=True)
class AlertPayload:
    """Provider-agnostic view of an alert. Providers format this into
    their own JSON shape; the dispatcher never calls a provider's
    specific format helper directly."""

    level: str
    level_emoji: str
    title: str
    message: str
    exchange: str | None
    symbol: str | None
    timestamp_iso: str
    level_threshold: str  # for diagnostics — the configured min level


# ── Three concrete providers ────────────────────────────────────


class FeishuProvider:
    """Feishu / Lark custom bot webhook.

    Payload shape:
        {"msg_type": "text", "content": {"text": "<level> <title>\n<body>"}}
    """

    name = "feishu"

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        if not webhook_url:
            raise ValueError("Feishu webhook_url is required")
        self._url = webhook_url
        self._timeout = timeout

    async def send(self, payload: AlertPayload) -> None:
        text = (
            f"{payload.level_emoji} [{payload.level.upper()}] {payload.title}\n"
            f"{payload.message}"
        )
        if payload.exchange or payload.symbol:
            ctx = " · ".join(filter(None, [payload.exchange, payload.symbol]))
            text += f"\nContext: {ctx}"
        text += f"\nTime: {payload.timestamp_iso}"
        body = {"msg_type": "text", "content": {"text": text}}
        await _post_json(self._url, body, self._timeout)


class DingTalkProvider:
    """DingTalk custom bot webhook.

    Payload shape:
        {"msgtype": "text", "text": {"content": "<level> <title>: <message>"}}
    """

    name = "dingtalk"

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        if not webhook_url:
            raise ValueError("DingTalk webhook_url is required")
        self._url = webhook_url
        self._timeout = timeout

    async def send(self, payload: AlertPayload) -> None:
        content = (
            f"{payload.level_emoji} [{payload.level.upper()}] {payload.title}: "
            f"{payload.message}"
        )
        if payload.exchange or payload.symbol:
            ctx = " · ".join(filter(None, [payload.exchange, payload.symbol]))
            content += f" ({ctx})"
        body = {"msgtype": "text", "text": {"content": content}}
        await _post_json(self._url, body, self._timeout)


class WeComProvider:
    """WeChat Work (企业微信) custom bot webhook.

    Payload shape:
        {"msgtype": "text", "text": {"content": "<level> <title>\n<message>"}}
    """

    name = "wecom"

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        if not webhook_url:
            raise ValueError("WeCom webhook_url is required")
        self._url = webhook_url
        self._timeout = timeout

    async def send(self, payload: AlertPayload) -> None:
        text = (
            f"{payload.level_emoji} [{payload.level.upper()}] {payload.title}\n"
            f"{payload.message}"
        )
        if payload.exchange or payload.symbol:
            ctx = " · ".join(filter(None, [payload.exchange, payload.symbol]))
            text += f"\nContext: {ctx}"
        text += f"\nTime: {payload.timestamp_iso}"
        body = {"msgtype": "text", "text": {"content": text}}
        await _post_json(self._url, body, self._timeout)


# ── Network helper ──────────────────────────────────────────────


async def _post_json(url: str, body: dict[str, Any], timeout: float) -> None:
    """POST JSON, raise on non-2xx. Errors are logged but never bubble
    up to the Monitor callback path — an alerting outage must not
    crash the engine loop."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            logger.warning(
                f"Alert webhook returned {resp.status_code}: {resp.text[:200]}"
            )
    except Exception as exc:
        logger.warning(f"Alert webhook send failed ({type(exc).__name__}): {exc}")


# ── Dispatcher ──────────────────────────────────────────────────


# Mapping AlertLevel → emoji prefix used in every provider's message
_LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.ERROR: "🔴",
    AlertLevel.CRITICAL: "🚨",
}


@dataclass
class DispatcherConfig:
    """Configuration for which providers are enabled and what to send."""

    min_level: AlertLevel = AlertLevel.WARNING
    feishu_url: str = ""
    dingtalk_url: str = ""
    wecom_url: str = ""
    http_timeout: float = 10.0


class AlertDispatcher:
    """Monitor callback that fans out alerts to one or more providers.

    Hook into the Monitor with:
        monitor.on_alert(dispatcher.handle_alert)

    Each `handle_alert` call schedules the provider network calls
    asynchronously and returns immediately — it must not block the
    Monitor's alert path.
    """

    def __init__(self, config: DispatcherConfig) -> None:
        self._config = config
        self._providers: list[AlertProvider] = []
        if config.feishu_url:
            self._providers.append(FeishuProvider(config.feishu_url, config.http_timeout))
        if config.dingtalk_url:
            self._providers.append(DingTalkProvider(config.dingtalk_url, config.http_timeout))
        if config.wecom_url:
            self._providers.append(WeComProvider(config.wecom_url, config.http_timeout))

    @property
    def providers(self) -> list[AlertProvider]:
        """Returns the list of configured providers (read-only)."""
        return list(self._providers)

    def _payload_for(self, alert: Alert) -> AlertPayload:
        return AlertPayload(
            level=alert.level.value,
            level_emoji=_LEVEL_EMOJI.get(alert.level, "•"),
            title=alert.title,
            message=alert.message,
            exchange=alert.exchange,
            symbol=alert.symbol,
            timestamp_iso=alert.timestamp.isoformat(),
            level_threshold=self._config.min_level.value,
        )

    async def handle_alert(self, alert: Alert) -> None:
        """Monitor callback. Filters by min_level then dispatches.

        Runs provider sends in parallel (asyncio.gather). Provider
        errors are swallowed by `_post_json` so a single broken
        provider doesn't take the others down.
        """
        if not self._providers:
            return
        if _level_rank(alert.level) < _level_rank(self._config.min_level):
            return

        payload = self._payload_for(alert)
        # Fire-and-forget: the Monitor callback path is sync-ish, so
        # schedule the network calls as a background task.
        await asyncio.gather(
            *(provider.send(payload) for provider in self._providers),
            return_exceptions=True,
        )

    def send_test(self, message: str = "Test alert from Quant Trader") -> None:
        """Synchronous test helper — sends a synthetic INFO alert to all
        enabled providers. Used by docs and the Settings page 'Test
        webhook' button."""
        from datetime import datetime
        alert = Alert(
            level=AlertLevel.INFO,
            category=AlertCategory.SYSTEM,
            title="Test alert",
            message=message,
            timestamp=datetime.utcnow(),
        )
        asyncio.run(self.handle_alert(alert))


def _level_rank(level: AlertLevel) -> int:
    """Numeric ordering so we can compare INFO < WARNING < ERROR < CRITICAL."""
    return {AlertLevel.INFO: 0, AlertLevel.WARNING: 1, AlertLevel.ERROR: 2, AlertLevel.CRITICAL: 3}[level]
