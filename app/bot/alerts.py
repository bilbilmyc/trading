"""主动告警订阅 — 把 Monitor 的 alert 推到 Telegram。

设计：
- ``BotAlertSubscriber`` 作为 Monitor 的 ``on_alert`` 回调被注册。
- 在 ``__call__`` 里同步过滤（cooldown 去重）后，把消息发送到 bot 编排器。
- 静默时段（quiet hours）只对 ``WARNING``/``INFO`` 生效——``ERROR`` /
  ``CRITICAL`` 始终绕过，避免用户在睡觉时出现真正的炸雷却被静音。

注意：这个模块不直接 import ``TradingBot``，避免循环依赖。
订阅者拿到的是一个 ``BotConfig`` + 一个 ``send_coro(chat_id, text)`` 工厂，
由编排器在启动时注入。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.bot.config import BotConfig
from app.bot.formatter import format_events

if TYPE_CHECKING:
    from app.engine.monitor import Alert


_LEVEL_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def _rank(name: str) -> int:
    return _LEVEL_RANK.get(name.lower(), 0)


@dataclass(frozen=True)
class _Seen:
    """记录上一次相同 fingerprint 的推送时间。"""

    last_sent_at: float


class BotAlertSubscriber:
    """Monitor 回调 + 推送去重 + 静默策略。

    用法::

        subscriber = BotAlertSubscriber(config=cfg, sender=bot.push_to_all)
        monitor.on_alert(subscriber.handle)   # 在 bot 启动前/同时注册
    """

    def __init__(
        self,
        config: BotConfig,
        sender: Callable[[str], Awaitable[None]],
        # 注入时钟便于测试。
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._sender = sender
        self._clock = clock or time.monotonic
        self._seen: dict[str, _Seen] = {}

    async def __call__(self, alert: Alert) -> None:
        """Monitor 异步回调入口。"""
        await self.handle(alert)

    async def handle(self, alert: Alert) -> None:
        """主体：过滤 → 去重 → 推送。"""
        min_level = self._config.min_alert_level
        if _rank(alert.level.value) < _rank(min_level):
            return

        fingerprint = self._fingerprint(alert)
        if self._is_cool_down(fingerprint):
            return

        now_hour = datetime.now().hour
        bypass_quiet = _rank(alert.level.value) >= _rank("error")
        if not bypass_quiet and self._config.in_quiet_hours(now_hour):
            return

        text = self._render(alert)
        try:
            await self._sender(text)
        finally:
            self._seen[fingerprint] = _Seen(last_sent_at=self._clock())

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(alert: Alert) -> str:
        """同一 (level, category, title) 在冷却窗口内只推一次。"""
        return f"{alert.level.value}:{alert.category.value}:{alert.title}"

    def _is_cool_down(self, fingerprint: str) -> bool:
        record = self._seen.get(fingerprint)
        if record is None:
            return False
        return (self._clock() - record.last_sent_at) < self._config.alert_fingerprint_cooldown_seconds

    @staticmethod
    def _render(alert: Alert) -> str:
        """复用 formatter：让单条 alert 长得和 ``/events`` 命令一致。"""
        events = {
            "events": [
                {
                    "event_type": str(alert.category.value),
                    "message": alert.message,
                    "level": str(alert.level.value),
                    "timestamp": alert.timestamp.isoformat()
                    if hasattr(alert.timestamp, "isoformat")
                    else str(alert.timestamp),
                }
            ]
        }
        # 在事件前面拼一行 title/exchange/symbol 让阅读上下文更清楚。
        header = (
            f"🚨 <b>{alert.title}</b>"
            f"{f' · {alert.exchange}' if alert.exchange else ''}"
            f"{f' · {alert.symbol}' if alert.symbol else ''}"
        )
        return f"{header}\n" + format_events(events)


__all__ = ["BotAlertSubscriber"]
