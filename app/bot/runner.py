"""Bot 编排器 — 把 provider / 命令路由 / 调度任务串起来。

这是 ``app/bot/`` 之前缺失的 "glue"：

- ``TradingBot.start()`` — 启动 provider，订阅 alert，注册后台任务。
- ``TradingBot.run_forever()`` — 主循环，poll / dispatch / respond，
  处理一切异常不让 loop 死掉。
- ``TradingBot.stop()`` — 优雅关闭所有后台任务和 provider。

命令调用、主动告警和每日报告分别在三个职责清晰的辅助模块里：

- :mod:`app.bot.commands` — ``dispatch`` + ``BotApiClient``
- :mod:`app.bot.alerts`   — 主动告警订阅（Phase 5 补完）
- :mod:`app.bot.scheduler` — 每日报告 + 静默时段（Phase 6 补完）
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from loguru import logger

from app.bot.commands import BotApiClient, dispatch
from app.bot.config import BotConfig
from app.bot.provider import BotProvider, IncomingMessage, OutgoingMessage


class TradingBot:
    """Bot 编排器。

    用法::

        cfg = bot_config_from_settings(settings)
        provider = TelegramProvider(cfg)
        bot = TradingBot(cfg, provider, monitor=engine.monitor)
        asyncio.run(bot.run_forever())

    关闭时调用 ``stop()``（已注册 ``atexit`` 兜底，但显式调用更安全）。
    """

    def __init__(
        self,
        config: BotConfig,
        provider: BotProvider,
        monitor: Any | None = None,
        *,
        alert_subscriber: Any | None = None,
        schedule_jobs: list[Any] | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._monitor = monitor
        self._api = BotApiClient(config)
        self._alert_subscriber = alert_subscriber
        self._schedule_jobs = list(schedule_jobs or [])
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._running = False

    @property
    def api(self) -> BotApiClient:
        """BotApiClient — 给调度任务（如日报）查询引擎状态用。"""
        return self._api

    @property
    def config(self) -> BotConfig:
        return self._config

    @property
    def monitor(self) -> Any:
        return self._monitor

    # ── 生命周期 ─────────────────────────────────────────────

    async def start(self) -> None:
        """启动 provider，注册 alert hook（可选）和后台任务。"""
        if self._running:
            return
        if not self._config.telegram_token:
            raise RuntimeError("BotConfig.telegram_token is empty; cannot start.")

        await self._provider.start()

        # Proactive alert forwarding — Phase 5 hook.
        if self._alert_subscriber is not None and self._monitor is not None:
            self._monitor.on_alert(self._alert_subscriber.handle)
            logger.info("Bot subscribed to monitor alerts")

        # Background scheduled tasks — Phase 6 hook (daily report etc.)
        for job in self._schedule_jobs:
            task = asyncio.create_task(job(self), name=job.__name__)
            self._background_tasks.append(task)

        self._running = True
        logger.info(
            f"Bot started: provider={self._provider.name} "
            f"allowed_chats={len(self._config.allowed_chat_ids) or 'ALL'}"
        )

    async def stop(self) -> None:
        """优雅关闭：取消后台任务、关闭 provider。"""
        if not self._running:
            return
        self._running = False
        for task in self._background_tasks:
            task.cancel()
        for task in self._background_tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._background_tasks.clear()
        await self._provider.stop()
        logger.info("Bot stopped")

    # ── 主循环 ───────────────────────────────────────────────

    async def run_forever(self) -> None:
        """主入口：start → poll 循环 → KeyboardInterrupt 时 stop。

        poll 自身可能在网络层失败；我们捕获所有异常，sleep 一下再重试，
        确保一次网络抖动不会让整个 bot 死掉。
        """
        await self.start()
        try:
            while self._running:
                try:
                    messages = await self._provider.poll()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(f"Bot poll failed: {exc!r}; backing off 2s")
                    await asyncio.sleep(2.0)
                    continue
                for msg in messages:
                    await self._handle_message(msg)
        finally:
            await self.stop()

    async def push_to_all(self, text: str, *, parse_mode: str = "HTML") -> None:
        """主动推一条消息到所有允许的 chat。供 alert scheduler 使用。"""
        targets = self._target_chat_ids()
        for chat_id in targets:
            await self._safe_send(chat_id, text, parse_mode=parse_mode)

    # ── 内部 ──────────────────────────────────────────────────

    def _target_chat_ids(self) -> list[int]:
        """所有需要推送的 chat id。

        - ``allowed_chat_ids`` 为空时，主动推送禁用（按需命令仍允许，因为是
          用户先发起请求）。
        - 否则遍历白名单。
        """
        if not self._config.allowed_chat_ids:
            return []
        return list(self._config.allowed_chat_ids)

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """处理一条入站消息：白名单 → 命令路由 → 回包。"""
        if not self._config.is_chat_allowed(msg.chat_id):
            logger.warning(
                f"Bot ignored message from chat_id={msg.chat_id} "
                f"(not in whitelist)"
            )
            return

        try:
            response = await dispatch(msg.text, self._api, msg.chat_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Bot dispatch failed for chat_id={msg.chat_id}")
            response = f"❌ 执行失败: {exc}"

        if response is None:
            return

        await self._safe_send(
            msg.chat_id,
            str(response),
            reply_to=msg.message_id,
        )

    async def _safe_send(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str = "HTML",
    ) -> None:
        """发送一条消息，吞掉所有异常 —— 不让单次发送失败影响主循环。"""
        try:
            await self._provider.send(
                OutgoingMessage(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Bot send failed to chat_id={chat_id}: {exc!r}")


__all__ = ["TradingBot"]
