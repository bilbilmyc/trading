"""Tests for app.bot — settings parsing, format, dispatch, lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.bot.alerts import BotAlertSubscriber
from app.bot.commands import BotApiClient, dispatch
from app.bot.config import BotConfig, bot_config_from_settings
from app.bot.formatter import (
    format_events,
    format_paper,
    format_positions,
    format_risk,
    format_status,
)
from app.bot.provider import IncomingMessage, OutgoingMessage
from app.bot.runner import TradingBot
from app.engine.monitor import Alert, AlertCategory, AlertLevel

# ── BotConfig & Settings parsing ────────────────────────────────


def test_settings_bot_property_has_expected_fields():
    from config import load_settings

    settings = load_settings()
    bot = settings.bot
    # Field names match the flat Settings fields.
    assert hasattr(bot, "enabled")
    assert hasattr(bot, "telegram_token")
    assert hasattr(bot, "allowed_chat_ids")
    assert hasattr(bot, "outbound_scope")
    # Default values are safe (disabled by default).
    assert bot.enabled is False
    assert bot.outbound_scope == "monitor"


def test_bot_config_from_settings_default_disabled():
    from config import load_settings

    cfg = bot_config_from_settings(load_settings())
    assert cfg.enabled is False
    assert cfg.api_key == ""  # No auth_api_key fallback unless set
    assert cfg.telegram_token == ""
    assert cfg.allowed_chat_ids == ()


def test_bot_config_quiet_hours_parsing_cross_midnight():
    from config import Settings

    settings = Settings(
        bot_enabled=True,
        bot_quiet_hours="22-8",
        bot_allowed_chat_ids="-100123,123456",
    )
    cfg = bot_config_from_settings(settings)
    assert cfg.quiet_hours == (22, 8)
    # Cross-midnight: 23:00 is quiet, 09:00 is not.
    assert cfg.in_quiet_hours(23) is True
    assert cfg.in_quiet_hours(9) is False
    # Plain interval also works.
    settings2 = Settings(bot_quiet_hours="0-8")
    cfg2 = bot_config_from_settings(settings2)
    assert cfg2.in_quiet_hours(7) is True
    assert cfg2.in_quiet_hours(9) is False


def test_is_chat_allowed_empty_list_means_open():
    cfg = BotConfig(allowed_chat_ids=())
    assert cfg.is_chat_allowed(123) is True
    assert cfg.is_chat_allowed(-100123456) is True


def test_is_chat_allowed_whitelist_enforced():
    cfg = BotConfig(allowed_chat_ids=(42, -1001234567890))
    assert cfg.is_chat_allowed(42) is True
    assert cfg.is_chat_allowed(-1001234567890) is True
    assert cfg.is_chat_allowed(99) is False


# ── Formatters (pure functions) ────────────────────────────────


def test_format_status_running_and_kill():
    text = format_status({
        "running": True,
        "exchanges": ["binance_usdm", "okx"],
        "strategies": ["sma_5_20"],
        "risk": {"daily_pnl": 12.5, "current_drawdown_pct": 0.05, "kill_switch_enabled": False},
        "positions": {"count": 3},
        "monitor": {"total_alerts": 7},
        "signal_runner": {"running": True},
    })
    assert "🟢" in text
    assert "binance_usdm" in text
    assert "+12.50" in text
    assert "3 个" in text
    assert "🚨" not in text


def test_format_status_kill_switch_shows_warning_emoji():
    text = format_status({
        "running": True,
        "exchanges": [],
        "strategies": [],
        "risk": {"kill_switch_enabled": True},
        "positions": {"count": 0},
        "monitor": {},
        "signal_runner": {},
    })
    assert "🚨 已启用" in text


def test_format_paper_basic():
    text = format_paper({
        "cash": 1000.0,
        "equity": 1100.0,
        "initial_cash": 1000.0,
        "positions": [],
        "realized_pnl": 50.0,
        "unrealized_pnl": 50.0,
    })
    assert "1000.00" in text
    assert "权益" in text


def test_format_positions_empty():
    assert "无持仓" in format_positions({"positions": []})


def test_format_risk_escape_html():
    text = format_risk({
        "kill_switch_enabled": False,
        "daily_pnl": -3.14,
        "trading_enabled": True,
    })
    assert "&lt;" not in text  # our risk formatter shouldn't need to escape


def test_format_events_escapes_payload():
    """Make sure attacker-controlled event messages get escaped."""
    dangerous = "<script>alert(1)</script>"
    text = format_events({
        "events": [
            {
                "event_type": "system",
                "message": dangerous,
                "level": "warning",
                "timestamp": "2026-07-15T12:00:00",
            }
        ]
    })
    assert "&lt;script&gt;" in text
    assert "<script>" not in text


# ── BotApiClient (X-Bot-Scope injection) ───────────────────────


def test_bot_api_client_injects_scope_header():
    cfg = BotConfig(api_key="secret", outbound_scope="telegram-bot-test")
    api = BotApiClient(cfg)
    assert api._headers["X-Bot-Scope"] == "telegram-bot-test"
    assert api._headers["Authorization"] == "Bearer secret"


def test_bot_api_client_skips_authorization_when_no_key():
    cfg = BotConfig(api_key="", outbound_scope="telegram-bot-test")
    api = BotApiClient(cfg)
    assert "Authorization" not in api._headers
    assert api._headers["X-Bot-Scope"] == "telegram-bot-test"


# ── dispatch (uses monkey-patched HTTP) ───────────────────────


class _RecordingClient:
    """Fake ``BotApiClient`` that records calls and returns scripted responses."""

    def __init__(self, responses: list[Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._responses = list(responses)

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        self.calls.append((path, None))
        return self._responses.pop(0) if self._responses else {}

    async def post(self, path: str, json_data: dict | None = None) -> dict[str, Any]:
        self.calls.append((path, json_data))
        return self._responses.pop(0) if self._responses else {}

    async def delete(self, path: str) -> dict[str, Any]:
        self.calls.append((path, None))
        return self._responses.pop(0) if self._responses else {}


@pytest.mark.asyncio
async def test_dispatch_routes_to_known_command():
    fake = _RecordingClient([{"running": True, "exchanges": [], "strategies": [], "risk": {}, "positions": {}, "monitor": {}, "signal_runner": {}}])
    text = await dispatch("/status", fake, chat_id=42)
    assert text is not None and "引擎状态" in text
    # Last call should target the status endpoint.
    assert fake.calls[-1][0] == "/api/v1/engine/status"


@pytest.mark.asyncio
async def test_dispatch_unknown_command_returns_error():
    fake = _RecordingClient([])
    text = await dispatch("/nosuchcommand", fake, chat_id=42)
    assert text is not None and "未知命令" in text
    # Unknown command must NOT issue any HTTP call.
    assert fake.calls == []


@pytest.mark.asyncio
async def test_dispatch_handles_http_status_error():
    class _BoomClient:
        def __init__(self):
            self.calls = 0

        async def get(self, path: str, **params: Any) -> dict[str, Any]:
            self.calls += 1
            request = httpx.Request("GET", "http://x/api/v1/engine/status")
            response = httpx.Response(500, json={"detail": "boom"}, request=request)
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    boom = _BoomClient()
    text = await dispatch("/status", boom, chat_id=42)
    assert text is not None and "API 错误" in text
    assert "500" in text


@pytest.mark.asyncio
async def test_dispatch_kill_command_gets_kill_switch_state():
    fake = _RecordingClient([{"enabled": False, "reason": "off"}])
    text = await dispatch("/kill", fake, chat_id=42)
    assert text is not None and "关闭" in text
    assert fake.calls[-1][0] == "/api/v1/risk/kill-switch"
    # GET (no JSON body).
    assert fake.calls[-1][1] is None


@pytest.mark.asyncio
async def test_dispatch_kill_command_on_posts_with_reason():
    fake = _RecordingClient([{"enabled": True, "reason": "manual"}])
    text = await dispatch("/kill on manual override", fake, chat_id=42)
    assert text is not None and "启用" in text
    path, body = fake.calls[-1]
    assert path == "/api/v1/risk/kill-switch"
    assert body == {"enabled": True, "reason": "manual override"}


# ── TradingBot lifecycle (with stub provider) ─────────────────


class _StubProvider:
    """Minimal BotProvider stub for orchestrator tests."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.inbox: list[IncomingMessage] = []
        self.started = False
        self.stopped = False
        self.poll_count = 0

    @property
    def name(self) -> str:
        return "stub"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)

    async def poll(self) -> list[IncomingMessage]:
        self.poll_count += 1
        msgs = list(self.inbox)
        self.inbox.clear()
        if not msgs and self.poll_count < 3:
            # Return empty for first 2 polls; then return inbox.
            await asyncio.sleep(0)
        return msgs


@pytest.mark.asyncio
async def test_trading_bot_replies_to_whitelisted_chat():
    cfg = BotConfig(
        enabled=True,
        telegram_token="dummy",
        allowed_chat_ids=(42,),
        api_base_url="http://x",
    )
    provider = _StubProvider()
    provider.inbox.append(
        IncomingMessage(chat_id=42, text="/help", message_id=100)
    )
    # /help does NOT hit any API endpoint; it returns static help text.
    bot = TradingBot(cfg, provider)
    await bot.start()
    # Run one loop iteration by manually invoking _handle_message.
    msg = provider.inbox.pop(0)
    await bot._handle_message(msg)
    await bot.stop()
    assert any("/status" in m.text and "help" in m.text.lower() or "/help" in m.text for m in provider.sent)
    # Provider stopped.
    assert provider.stopped is True


@pytest.mark.asyncio
async def test_trading_bot_rejects_unwhitelisted_chat():
    cfg = BotConfig(
        enabled=True,
        telegram_token="dummy",
        allowed_chat_ids=(42,),
        api_base_url="http://x",
    )
    provider = _StubProvider()
    bot = TradingBot(cfg, provider)
    await bot.start()
    await bot._handle_message(IncomingMessage(chat_id=99, text="/help"))
    await bot.stop()
    assert provider.sent == []  # nothing sent back


@pytest.mark.asyncio
async def test_trading_bot_refuses_to_start_without_token():
    cfg = BotConfig(enabled=True, telegram_token="", api_base_url="http://x")
    provider = _StubProvider()
    bot = TradingBot(cfg, provider)
    with pytest.raises(RuntimeError, match="telegram_token"):
        await bot.start()


# ── BotAlertSubscriber (filter, cooldown, quiet hours) ──────────


@pytest.mark.asyncio
async def test_alert_subscriber_filters_below_min_level():
    cfg = BotConfig(min_alert_level="error")
    sent: list[str] = []
    sub = BotAlertSubscriber(cfg, sender=_capture(sent))
    info = Alert(level=AlertLevel.INFO, category=AlertCategory.SYSTEM, title="hi", message="")
    await sub.handle(info)
    assert sent == []


@pytest.mark.asyncio
async def test_alert_subscriber_dedupes_within_cooldown():
    cfg = BotConfig(min_alert_level="warning", alert_fingerprint_cooldown_seconds=600)
    sent: list[str] = []
    sub = BotAlertSubscriber(cfg, sender=_capture(sent), clock=lambda: 1000.0)
    alert = Alert(level=AlertLevel.ERROR, category=AlertCategory.EXCHANGE, title="ping failed", message="x")
    await sub.handle(alert)  # first push
    await sub.handle(alert)  # inside cooldown window → skip
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_alert_subscriber_bypasses_quiet_for_critical():
    cfg = BotConfig(
        min_alert_level="warning",
        quiet_hours=(0, 24),  # whole day is quiet
    )
    sent: list[str] = []
    sub = BotAlertSubscriber(cfg, sender=_capture(sent))
    crit = Alert(level=AlertLevel.CRITICAL, category=AlertCategory.EXCHANGE, title="down", message="")
    warn = Alert(level=AlertLevel.WARNING, category=AlertCategory.EXCHANGE, title="slow", message="")
    await sub.handle(crit)
    await sub.handle(warn)
    assert len(sent) == 1  # only critical bypasses quiet


@pytest.mark.asyncio
async def test_alert_subscriber_renders_title_and_exchange():
    cfg = BotConfig(min_alert_level="warning")
    sent: list[str] = []
    sub = BotAlertSubscriber(cfg, sender=_capture(sent))
    alert = Alert(
        level=AlertLevel.ERROR,
        category=AlertCategory.RISK,
        title="Trading disabled",
        message="Daily loss too high",
        exchange="binance_usdm",
        symbol="BTCUSDT",
    )
    await sub.handle(alert)
    assert "Trading disabled" in sent[0]
    assert "binance_usdm" in sent[0]
    assert "&lt;" not in sent[0]  # the title had no HTML, but defense-in-depth


def _capture(sink: list[str]):
    async def _send(text: str) -> None:
        sink.append(text)

    return _send


# ── Quick smoke: app.bot package is importable ────────────────


def test_bot_package_imports_cleanly():
    # Imports all submodules; if any import is broken this fails.
    from app.bot import (  # noqa: F401
        alerts,
        commands,
        config,
        formatter,
        provider,
        runner,
        scheduler,
        telegram,
    )
