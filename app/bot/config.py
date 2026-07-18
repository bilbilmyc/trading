"""Bot 配置 + chat 授权。

从 ``settings.bot`` (一个已经聚合好的 ``BotSettings``) 直接读字段，
不再做 getattr 反射 —— ``Settings`` 现在已经显式声明了所有 bot_*
字段并通过 ``Settings.bot`` property 暴露。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    enabled: bool = False
    telegram_token: str = ""
    allowed_chat_ids: tuple[int, ...] = ()
    api_base_url: str = "http://127.0.0.1:8000"
    api_key: str = ""
    request_timeout_seconds: float = 10.0
    event_poll_interval_seconds: float = 5.0
    daily_report_enabled: bool = True
    daily_report_hour: int = 0
    daily_report_minute: int = 5
    quiet_hours: tuple[int, int] | None = None
    send_rate_per_second: float = 4.0
    min_alert_level: str = "warning"
    alert_fingerprint_cooldown_seconds: int = 300
    outbound_scope: str = "monitor"
    autopilot_enabled: bool = False
    autopilot_live_order_enabled: bool = False
    autopilot_exchange: str = "binance_usdm"
    autopilot_symbols: tuple[str, ...] = ()
    autopilot_cycle_seconds: int = 300
    autopilot_min_return_pct: float = 0.002
    autopilot_max_order_notional: float = 25.0
    autopilot_max_daily_notional: float = 100.0

    def is_chat_allowed(self, chat_id: int) -> bool:
        """白名单：空列表 == 允许所有 chat（仅当显式 trust_open 也为真才推荐）。"""
        if not self.allowed_chat_ids:
            return True
        return chat_id in self.allowed_chat_ids

    def in_quiet_hours(self, hour: int) -> bool:
        """支持跨日静默（如 22-8 表示 22:00 到次日 08:00）。"""
        if self.quiet_hours is None:
            return False
        start, end = self.quiet_hours
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end


def bot_config_from_settings(settings) -> BotConfig:
    """从 settings.bot (BotSettings) 直接构造 BotConfig。

    ``settings.bot`` 是 Pydantic 模型，字段已类型化、可空安全、可单元测试。
    """
    bot = getattr(settings, "bot", None)
    if bot is None:
        # settings 没定义 bot property（老版本 settings.py）；fallback 到全默认。
        return BotConfig()
    return BotConfig(
        enabled=bool(bot.enabled),
        telegram_token=str(bot.telegram_token or ""),
        allowed_chat_ids=tuple(bot.allowed_chat_ids or ()),
        api_base_url=str(bot.api_base_url),
        api_key=str(bot.api_key or ""),
        request_timeout_seconds=float(bot.request_timeout_seconds),
        event_poll_interval_seconds=float(bot.event_poll_interval_seconds),
        daily_report_enabled=bool(bot.daily_report_enabled),
        daily_report_hour=int(bot.daily_report_hour),
        daily_report_minute=int(bot.daily_report_minute),
        quiet_hours=tuple(bot.quiet_hours) if bot.quiet_hours is not None else None,
        send_rate_per_second=float(bot.send_rate_per_second),
        min_alert_level=str(bot.min_alert_level),
        alert_fingerprint_cooldown_seconds=int(bot.alert_fingerprint_cooldown_seconds),
        outbound_scope=str(bot.outbound_scope),
        autopilot_enabled=bool(bot.autopilot_enabled),
        autopilot_live_order_enabled=bool(bot.autopilot_live_order_enabled),
        autopilot_exchange=str(bot.autopilot_exchange),
        autopilot_symbols=tuple(bot.autopilot_symbols or ()),
        autopilot_cycle_seconds=int(bot.autopilot_cycle_seconds),
        autopilot_min_return_pct=float(bot.autopilot_min_return_pct),
        autopilot_max_order_notional=float(bot.autopilot_max_order_notional),
        autopilot_max_daily_notional=float(bot.autopilot_max_daily_notional),
    )
